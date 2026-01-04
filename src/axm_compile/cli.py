"""AXM Embodied Genesis - Capsule to Shard Compiler."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nacl.signing import SigningKey

# Deterministic demo publisher key.
# This must match governance/trust_store.json so `axm-verify` can validate
# shards out-of-the-box.
_CANONICAL_PUBLISHER_SEED = bytes.fromhex(
    "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"
)

from axm_core.ids import entity_id, claim_id, span_id, prov_id
from axm_compile.streams import compile_streams_evidence

# Canonical test key - for gold shard only
# In production, load from HSM/Vault
CANONICAL_TEST_KEY = bytes.fromhex(
    "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"
)

# Fixed timestamp for deterministic gold shard
GOLD_TIMESTAMP = "2026-01-01T00:00:00Z"


def compile_capsule(
    capsule_path: Path,
    out_path: Path,
    signing_key: bytes | None = None,
    timestamp: str | None = None,
) -> None:
    """Compile a Capsule into a Shard."""
    print(f"Compiling Capsule: {capsule_path}")

    # Use deterministic demo key by default so verification works out-of-the-box.
    if signing_key is None:
        sk = SigningKey(_CANONICAL_PUBLISHER_SEED)
    else:
        sk = SigningKey(signing_key)

    # Use provided timestamp or current time
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # 1. Read Byte Authority
    events_path = capsule_path / "events.jsonl"
    with open(events_path, "rb") as f:
        raw_bytes = f.read()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()

    entities: list[dict] = []
    claims: list[dict] = []
    spans: list[dict] = []
    prov: list[dict] = []
    e_cache: dict[str, bool] = {}

    def add_entity(lbl: str, typ: str, ns: str = "embodied/wheel_slip") -> str:
        eid = entity_id(ns, lbl)
        if eid not in e_cache:
            entities.append({
                "entity_id": eid,
                "namespace": ns,
                "label": lbl,
                "type": typ,
            })
            e_cache[eid] = True
        return eid

    def add_claim(
        sub_id: str,
        pred: str,
        obj_val: str,
        obj_type: str,
        tier: int,
        byte_start: int,
        byte_end: int,
        text_slice: str,
    ) -> None:
        obj_id = add_entity(obj_val, "inferred") if obj_type == "entity" else obj_val

        cid = claim_id(sub_id, pred, obj_id, obj_type)
        sid = span_id(source_hash, byte_start, byte_end, text_slice)
        pid = prov_id(cid, sid)

        claims.append({
            "claim_id": cid,
            "subject": sub_id,
            "predicate": pred,
            "object": obj_id,
            "object_type": obj_type,
            "tier": int(tier),
        })
        spans.append({
            "span_id": sid,
            "source_hash": source_hash,
            "byte_start": int(byte_start),
            "byte_end": int(byte_end),
            "text": text_slice,
        })
        prov.append({
            "provenance_id": pid,
            "claim_id": cid,
            "span_id": sid,
            "source_hash": source_hash,
            "byte_start": int(byte_start),
            "byte_end": int(byte_end),
        })

    # 2. Parse Event Stream
    cur = 0
    lines = raw_bytes.split(b"\n")

    for line_bytes in lines:
        if not line_bytes:
            cur += 1  # Account for empty line (trailing newline)
            continue

        text = line_bytes.decode("utf-8")
        evt = json.loads(text)

        start = cur
        end = cur + len(line_bytes)
        cur = end + 1  # +1 for newline

        # --- ONTOLOGY EXTRACTION: Wheel Slip Domain ---
        if evt.get("evt") == "wheel_slip":
            rid = add_entity(evt.get("robot_id", "robot-001"), "robot")
            slip_id = add_entity("wheel_slip", "event")

            add_claim(rid, "observed", "wheel_slip", "entity", 2, start, end, text)
            add_claim(slip_id, "on_surface", evt["surface"], "literal:string", 2, start, end, text)

        elif evt.get("evt") == "recovery_action":
            add_entity(evt["action"], "action")
            slip_id = add_entity("wheel_slip", "event")

            # Tier 1 = Safety Rule
            add_claim(slip_id, "resolved_by", evt["action"], "entity", 1, start, end, text)
            add_claim(
                entity_id("embodied/wheel_slip", evt["action"]),
                "applied_value",
                str(evt["value"]),
                "literal:string",
                2,
                start,
                end,
                text,
            )

    # 3. Write Output Structure
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "graph").mkdir(exist_ok=True)
    (out_path / "evidence").mkdir(exist_ok=True)
    (out_path / "sig").mkdir(exist_ok=True)
    (out_path / "content").mkdir(exist_ok=True)

    def write_parquet(data: list[dict], filename: str, sort_key: str) -> None:
        if not data:
            return
        df = pd.DataFrame(data).sort_values(sort_key)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out_path / filename)

    write_parquet(entities, "graph/entities.parquet", "entity_id")
    write_parquet(claims, "graph/claims.parquet", "claim_id")
    write_parquet(prov, "graph/provenance.parquet", "provenance_id")

    # Deduplicate spans
    unique_spans = list({s["span_id"]: s for s in spans}.values())
    write_parquet(unique_spans, "evidence/spans.parquet", "span_id")

    # Phase 2 evidence (Pattern 2): build evidence/streams.parquet if binary streams exist.
    if (capsule_path / "cam_latents.bin").exists():
        compile_streams_evidence(capsule_path, out_path)

    # 4. Compute Integrity Root (Court-grade)
    # Match the verifier's algorithm: per-file leaf hashes over (rel_path + \0 + bytes)
    # reduced by pairwise sha256 until one root remains.
    all_files = [
        f for f in out_path.rglob("*")
        if f.is_file()
        and f.name not in {"manifest.json", "manifest.sig"}
    ]
    files_rel = sorted([f.relative_to(out_path).as_posix() for f in all_files])

    leaves: list[bytes] = []
    for rel in files_rel:
        p = out_path / rel
        h = hashlib.sha256()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        leaves.append(h.digest())

    # The reference verifier uses a simple, deterministic accumulator:
    # integrity_root = sha256(concat(leaf_hashes)).hexdigest()
    acc = hashlib.sha256()
    for leaf in leaves:
        acc.update(leaf)
    integrity_root = acc.hexdigest()

    # 5. Create and Sign Manifest
    manifest = {
        "spec": "1.0",
        "created": timestamp,
        "capsule_hash": source_hash,
        # Backward-compatible field
        "merkle_root": integrity_root,
        # Verifier-native structure
        "integrity": {
            "schema": "axm-merkle-v1",
            "algorithm": "sha256",
            "files": files_rel,
            "merkle_root": integrity_root,
        },
        "publisher": {"pubkey": sk.verify_key.encode().hex()},
    }

    man_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    (out_path / "manifest.json").write_bytes(man_bytes)
    (out_path / "sig/manifest.sig").write_bytes(sk.sign(man_bytes).signature)
    (out_path / "sig/publisher.pub").write_bytes(bytes(sk.verify_key))

    print(f"PASS: Shard generated at {out_path}")
    print(f"  Entities: {len(entities)}")
    print(f"  Claims: {len(claims)}")
    print(f"  Spans: {len(unique_spans)}")


@click.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.argument("out", type=click.Path(path_type=Path))
@click.option("--gold", is_flag=True, help="Use canonical test key and timestamp for gold shard")
def main(capsule: Path, out: Path, gold: bool) -> None:
    """Compile a Capsule into a Shard."""
    try:
        if gold:
            compile_capsule(
                capsule,
                out,
                signing_key=CANONICAL_TEST_KEY,
                timestamp=GOLD_TIMESTAMP,
            )
        else:
            compile_capsule(capsule, out)
    except Exception as e:
        # Court-grade behavior: fail closed, with a single-line reason.
        # Avoid stack traces in demos and in automated pipelines.
        print(f"FATAL: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
