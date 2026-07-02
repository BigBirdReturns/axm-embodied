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
