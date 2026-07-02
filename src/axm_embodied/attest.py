"""Incident attestation — proof of *when*, queued at seal time.

A shard's signature proves *who* sealed it, never *when*. Twenty years
into a product-liability tail, the argument you must defeat is "this
record was fabricated later with a leaked key." The standard answer
(mirroring the kernel's ``attestations/`` for the gold shard) is an
out-of-band timestamp proof over the manifest bytes: the manifest commits
to the Merkle root, and the Merkle root commits to every byte of the
shard, so timestamping ~1 KB of manifest pins the whole record in time.

Robots do not have guaranteed connectivity at the moment of a crash, so
attestation is split in two:

- **queue** (offline, at seal time): copy the manifest bytes into a queue
  entry, record the digests and the derived ``sh1_`` id, and pre-encode
  the exact RFC 3161 timestamp query (`.tsq`). The query bytes are fixed
  the moment the incident is sealed — whatever anchors later, *what* is
  being timestamped can no longer change.
- **flush** (whenever connectivity returns): POST each pending query to a
  time-stamping authority and store the signed response (`.tsr`) beside
  the query. OpenTimestamps anchoring can be layered on the same entry
  with the external ``ots`` tool.

Verification, decades later, needs only the shard, the entry, and the
TSA's public certificate chain::

    openssl ts -verify -queryfile entry/manifest.tsq \\
        -in entry/manifest.tsr -CAfile tsa-cacert.pem
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import blake3

# Default TSA: same free RFC 3161 authority the kernel's gold-shard
# attestation used. Override for a production TSA contract.
DEFAULT_TSA_URL = "https://freetsa.org/tsr"

_SHA256_OID = bytes.fromhex("0609608648016503040201")  # 2.16.840.1.101.3.4.2.1


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _der(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(content)) + content


def encode_tsq(digest_sha256: bytes) -> bytes:
    """Encode an RFC 3161 TimeStampReq (version 1, SHA-256, certReq TRUE).

    Deterministic, dependency-free DER. Equivalent to::

        openssl ts -query -sha256 -digest <hex> -cert

    (modulo the optional nonce, which we omit so the query bytes are a
    pure function of the shard — reproducible from the shard alone).
    """
    if len(digest_sha256) != 32:
        raise ValueError("digest must be 32 SHA-256 bytes")
    alg = _der(0x30, _der(0x06, _SHA256_OID[2:]) + _der(0x05, b""))
    imprint = _der(0x30, alg + _der(0x04, digest_sha256))
    version = _der(0x02, b"\x01")
    cert_req = _der(0x01, b"\xff")
    return _der(0x30, version + imprint + cert_req)


@dataclass(frozen=True)
class AttestationEntry:
    """One queued attestation: a shard pinned, awaiting anchors."""
    path: Path
    shard_id: str
    manifest_sha256: str
    anchored: bool


def queue_attestation(shard_dir: Path | str, queue_dir: Path | str,
                      note: str = "") -> AttestationEntry:
    """Queue a shard for out-of-band timestamp anchoring. Offline, cheap.

    Writes ``<queue>/<sh1 id>/`` containing:

    - ``manifest.json``  — byte-identical copy of the shard manifest
    - ``manifest.tsq``   — pre-encoded RFC 3161 query over its SHA-256
    - ``record.json``    — digests, derived shard id, queue-time metadata

    ``queued_at`` is the robot's own clock and proves nothing; the proof
    of time is whatever anchor later covers ``manifest.tsq``/``.ots``.
    """
    shard_dir = Path(shard_dir)
    queue_dir = Path(queue_dir)
    manifest_bytes = (shard_dir / "manifest.json").read_bytes()

    shard_id = "sh1_" + blake3.blake3(manifest_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).digest()
    manifest = json.loads(manifest_bytes)

    entry_dir = queue_dir / shard_id
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / "manifest.json").write_bytes(manifest_bytes)
    (entry_dir / "manifest.tsq").write_bytes(encode_tsq(manifest_sha256))

    record = {
        "shard_id": shard_id,
        "manifest_sha256": manifest_sha256.hex(),
        "merkle_root": manifest["integrity"]["merkle_root"],
        "publisher_id": manifest["publisher"]["id"],
        "created_at_claimed": manifest["metadata"]["created_at"],
        "queued_at_local_clock": datetime.now(timezone.utc)
        .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "note": note,
        "anchors": [],
    }
    (entry_dir / "record.json").write_text(json.dumps(record, indent=2) + "\n")

    return AttestationEntry(
        path=entry_dir,
        shard_id=shard_id,
        manifest_sha256=manifest_sha256.hex(),
        anchored=False,
    )


def list_queue(queue_dir: Path | str) -> List[AttestationEntry]:
    queue_dir = Path(queue_dir)
    out: List[AttestationEntry] = []
    if not queue_dir.is_dir():
        return out
    for entry_dir in sorted(queue_dir.iterdir()):
        if not (entry_dir / "record.json").exists():
            continue
        record = json.loads((entry_dir / "record.json").read_text())
        out.append(AttestationEntry(
            path=entry_dir,
            shard_id=record["shard_id"],
            manifest_sha256=record["manifest_sha256"],
            anchored=(entry_dir / "manifest.tsr").exists(),
        ))
    return out


def flush_queue(queue_dir: Path | str, tsa_url: str = DEFAULT_TSA_URL,
                timeout: float = 30.0) -> List[dict]:
    """Anchor every un-anchored entry: POST its .tsq to the TSA, store .tsr.

    Best-effort by design — a robot in the field retries on the next
    flush. Returns one result dict per pending entry.
    """
    results: List[dict] = []
    for entry in list_queue(queue_dir):
        if entry.anchored:
            continue
        tsq = (entry.path / "manifest.tsq").read_bytes()
        result = {"shard_id": entry.shard_id, "tsa": tsa_url}
        try:
            req = urllib.request.Request(
                tsa_url, data=tsq,
                headers={"Content-Type": "application/timestamp-query"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                tsr = resp.read()
            (entry.path / "manifest.tsr").write_bytes(tsr)
            record_path = entry.path / "record.json"
            record = json.loads(record_path.read_text())
            record["anchors"].append({
                "kind": "rfc3161",
                "tsa": tsa_url,
                "anchored_at_local_clock": datetime.now(timezone.utc)
                .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "response_file": "manifest.tsr",
            })
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            result["status"] = "ANCHORED"
        except Exception as e:  # noqa: BLE001 — field code, report and continue
            result["status"] = "PENDING"
            result["error"] = str(e)
        results.append(result)
    return results


def extract_rfc3161_gentime(tsr_bytes: bytes) -> Optional[str]:
    """Pull the TSA-asserted genTime out of an RFC 3161 response.

    In a TimeStampResp, the TSTInfo (which carries genTime as a DER
    GeneralizedTime, tag 0x18, ``YYYYMMDDHHMMSSZ``) sits inside
    encapContentInfo, which precedes the certificates in SignedData — so
    the first well-formed GeneralizedTime in the byte stream is genTime.
    Returns RFC 3339 UTC, or None if no plausible genTime is found. The
    raw response stays authoritative either way.
    """
    i = 0
    while True:
        i = tsr_bytes.find(b"\x18\x0f", i)
        if i == -1:
            return None
        v = tsr_bytes[i + 2:i + 17]
        if len(v) == 15 and v[:14].isdigit() and v[14:15] == b"Z":
            s = v.decode("ascii")
            return (f"{s[0:4]}-{s[4:6]}-{s[6:8]}T"
                    f"{s[8:10]}:{s[10:12]}:{s[12:14]}Z")
        i += 2


def build_attestation_shard(entry_dir: Path | str, out_dir: Path | str,
                            secret_key: bytes,
                            publisher_id: str = "@axm_embodied",
                            publisher_name: str = "AXM Embodied",
                            timestamp: Optional[str] = None) -> str:
    """Compile an anchored queue entry into an attestation shard (RFC 0005).

    The proof that the target existed at a point in time becomes an
    ordinary, signed, citable v1 shard: the raw RFC 3161 query/response
    and the target-manifest copy in ``content/``, machine-readable anchor
    metadata in ``ext/attestations@1.jsonl``, and a ``references@1`` row
    citing the target by ``sh1_`` id. Returns the attestation shard's own
    derived id.
    """
    import tempfile

    from axm_build.compiler_generic import CompilerConfig, compile_generic_shard

    entry_dir = Path(entry_dir)
    out_dir = Path(out_dir)
    if not verify_entry_matches_shard(entry_dir):
        raise ValueError(f"attestation entry is internally inconsistent: {entry_dir}")
    tsr_path = entry_dir / "manifest.tsr"
    if not tsr_path.exists():
        raise FileNotFoundError(
            f"entry is not anchored yet (no manifest.tsr): {entry_dir} — "
            f"run `axm-runtime attest-flush` first"
        )

    record = json.loads((entry_dir / "record.json").read_text())
    target_id = record["shard_id"]
    digest = record["manifest_sha256"]
    anchor = next((a for a in record["anchors"] if a["kind"] == "rfc3161"), {})
    authority = anchor.get("tsa", DEFAULT_TSA_URL)
    anchored_at = (extract_rfc3161_gentime(tsr_path.read_bytes())
                   or anchor.get("anchored_at_local_clock", ""))

    source_text = "\n".join([
        "ATTESTATION RECORD: PROOF OF EXISTENCE",
        "======================================",
        f"target: {target_id}",
        f"digest_sha256: {digest}",
        f"kind: rfc3161 authority: {authority} gen_time: {anchored_at}",
        "The raw proof (content/manifest.tsr) is authoritative; verify with:",
        "openssl ts -verify -queryfile manifest.tsq -in manifest.tsr -CAfile <tsa-ca>",
    ]) + "\n"

    candidates = []
    for pred, obj, ev in [
        ("target_shard_id", target_id, f"target: {target_id}"),
        ("digest_sha256", digest, f"digest_sha256: {digest}"),
        ("anchor_kind", "rfc3161",
         f"kind: rfc3161 authority: {authority} gen_time: {anchored_at}"),
        ("anchor_authority", authority,
         f"kind: rfc3161 authority: {authority} gen_time: {anchored_at}"),
        ("anchored_at", anchored_at,
         f"kind: rfc3161 authority: {authority} gen_time: {anchored_at}"),
    ]:
        cand = {
            "subject": f"anchor/{target_id}",
            "predicate": pred,
            "object": obj,
            "object_type": "literal:string",
            "tier": 1,
            "evidence": ev,
        }
        if pred == "target_shard_id":
            cand["references"] = [{
                "dst_shard_id": target_id,
                "relation_type": "cites",
                "dst_object_type": "shard",
                "dst_object_id": "",
                "confidence": "1.0",
                "note": "shard whose existence this attestation anchors in time",
            }]
        candidates.append(cand)

    ext_rows = [{
        "target_shard_id": target_id,
        "kind": "rfc3161",
        "authority": authority,
        "digest_sha256": digest,
        "anchored_at": anchored_at,
        "proof_path": "content/manifest.tsr",
    }]

    with tempfile.TemporaryDirectory(prefix="axm_attest_") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "source.txt").write_text(source_text, encoding="utf-8")
        with (tmp_path / "candidates.jsonl").open("w", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        cfg = CompilerConfig(
            source_path=tmp_path / "source.txt",
            candidates_path=tmp_path / "candidates.jsonl",
            out_dir=out_dir,
            private_key=secret_key,
            publisher_id=publisher_id,
            publisher_name=publisher_name,
            namespace="embodied/attestation",
            created_at=timestamp or datetime.now(timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            title=f"Attestation of {target_id}",
            license_spdx="Apache-2.0",
            extra_content=(
                ("target-manifest.json", entry_dir / "manifest.json"),
                ("manifest.tsq", entry_dir / "manifest.tsq"),
                ("manifest.tsr", tsr_path),
            ),
            extra_ext={"attestations@1": ext_rows},
        )
        if not compile_generic_shard(cfg):
            raise RuntimeError("kernel rejected the attestation shard")

    return "sh1_" + blake3.blake3((out_dir / "manifest.json").read_bytes()).hexdigest()


def verify_entry_matches_shard(entry_dir: Path | str,
                               shard_dir: Optional[Path | str] = None) -> bool:
    """Check internal consistency: tsq digest == manifest copy == record,
    and (optionally) that the copy is byte-identical to the live shard."""
    entry_dir = Path(entry_dir)
    manifest_bytes = (entry_dir / "manifest.json").read_bytes()
    digest = hashlib.sha256(manifest_bytes).digest()
    record = json.loads((entry_dir / "record.json").read_text())

    if record["manifest_sha256"] != digest.hex():
        return False
    if record["shard_id"] != "sh1_" + blake3.blake3(manifest_bytes).hexdigest():
        return False
    if (entry_dir / "manifest.tsq").read_bytes() != encode_tsq(digest):
        return False
    if shard_dir is not None:
        if (Path(shard_dir) / "manifest.json").read_bytes() != manifest_bytes:
            return False
    return True
