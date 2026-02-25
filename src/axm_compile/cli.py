"""AXM Embodied Genesis - Capsule to Shard Compiler.

v1.1 adds multi-suite support via the canonical axm-core signing layer:

  --suite axm-blake3-mldsa44   (default) ML-DSA-44 + domain-separated BLAKE3
  --suite ed25519              (legacy)  Ed25519 + legacy BLAKE3
  --legacy                     alias for --suite ed25519
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from axm_core.ids import entity_id, claim_id, span_id, prov_id
from axm_compile.streams import compile_streams_evidence

# ── Canonical signing layer ───────────────────────────────────────────────
from axm_build.sign import (
    signing_key_from_private_key_bytes,
    mldsa44_keygen,
    MLDSAKeyPair,
    SUITE_ED25519,
    SUITE_MLDSA44,
)
from axm_build.merkle import compute_merkle_root
from axm_build.manifest import dumps_canonical_json

# ── Canonical demo key (Ed25519, matches governance/trust_store.json) ────
_CANONICAL_PUBLISHER_SEED = bytes.fromhex(
    "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"
)
CANONICAL_TEST_KEY = _CANONICAL_PUBLISHER_SEED
GOLD_TIMESTAMP = "2026-01-01T00:00:00Z"


def compile_capsule(
    capsule_path: Path,
    out_path: Path,
    signing_key: bytes | None = None,
    timestamp: str | None = None,
    suite: str = SUITE_MLDSA44,
) -> None:
    """Compile a Capsule into a Shard.

    suite: SUITE_MLDSA44 (default, post-quantum) or SUITE_ED25519 (legacy)
    """
    print(f"Compiling Capsule: {capsule_path}")
    print(f"  Suite: {suite}")

    # ── Build signing key ─────────────────────────────────────────────────
    if suite == SUITE_MLDSA44:
        keypair: MLDSAKeyPair = mldsa44_keygen()
        sign_fn = keypair.sign
        pub_bytes = keypair.verify_key_bytes
    else:
        ed_sk = signing_key_from_private_key_bytes(signing_key or _CANONICAL_PUBLISHER_SEED)
        sign_fn = lambda msg: ed_sk.sign(msg).signature
        pub_bytes = bytes(ed_sk.verify_key)

    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )

    # ── 1. Read Byte Authority ────────────────────────────────────────────
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
            entities.append({"entity_id": eid, "namespace": ns, "label": lbl, "type": typ})
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
            "claim_id": cid, "subject": sub_id, "predicate": pred,
            "object": obj_id, "object_type": obj_type, "tier": int(tier),
        })
        spans.append({
            "span_id": sid, "source_hash": source_hash,
            "byte_start": int(byte_start), "byte_end": int(byte_end), "text": text_slice,
        })
        prov.append({
            "provenance_id": pid, "claim_id": cid, "span_id": sid,
            "source_hash": source_hash,
            "byte_start": int(byte_start), "byte_end": int(byte_end),
        })

    # ── 2. Parse Event Stream ─────────────────────────────────────────────
    cur = 0
    for line_bytes in raw_bytes.split(b"\n"):
        if not line_bytes:
            cur += 1
            continue

        text = line_bytes.decode("utf-8")
        evt = json.loads(text)
        start = cur
        end = cur + len(line_bytes)
        cur = end + 1

        if evt.get("evt") == "wheel_slip":
            rid = add_entity(evt.get("robot_id", "robot-001"), "robot")
            slip_id = add_entity("wheel_slip", "event")
            add_claim(rid, "observed", "wheel_slip", "entity", 2, start, end, text)
            add_claim(slip_id, "on_surface", evt["surface"], "literal:string", 2, start, end, text)

        elif evt.get("evt") == "recovery_action":
            add_entity(evt["action"], "action")
            slip_id = add_entity("wheel_slip", "event")
            add_claim(slip_id, "resolved_by", evt["action"], "entity", 1, start, end, text)
            add_claim(
                entity_id("embodied/wheel_slip", evt["action"]),
                "applied_value", str(evt["value"]), "literal:string",
                2, start, end, text,
            )

    # ── 3. Write Output Structure ─────────────────────────────────────────
    out_path.mkdir(parents=True, exist_ok=True)
    for d in ("graph", "evidence", "sig", "content"):
        (out_path / d).mkdir(exist_ok=True)

    def write_parquet(data: list[dict], filename: str, sort_key: str) -> None:
        if not data:
            return
        df = pd.DataFrame(data).sort_values(sort_key)
        pq.write_table(
            pa.Table.from_pandas(df, preserve_index=False), out_path / filename
        )

    write_parquet(entities, "graph/entities.parquet", "entity_id")
    write_parquet(claims, "graph/claims.parquet", "claim_id")
    write_parquet(prov, "graph/provenance.parquet", "provenance_id")

    unique_spans = list({s["span_id"]: s for s in spans}.values())
    write_parquet(unique_spans, "evidence/spans.parquet", "span_id")

    if (capsule_path / "cam_latents.bin").exists():
        compile_streams_evidence(capsule_path, out_path)

    # ── 4. Compute Merkle Root (canonical algorithm) ──────────────────────
    integrity_root = compute_merkle_root(out_path, suite=suite)

    # ── 5. Create and Sign Manifest ───────────────────────────────────────
    manifest: dict = {
        "spec": "1.0",
        "suite": suite,
        "created": timestamp,
        "capsule_hash": source_hash,
        "merkle_root": integrity_root,
        "integrity": {
            "schema": "axm-merkle-v1",
            "algorithm": "blake3",
            "merkle_root": integrity_root,
        },
        "publisher": {"pubkey": pub_bytes.hex()},
    }

    man_bytes = dumps_canonical_json(manifest)

    (out_path / "manifest.json").write_bytes(man_bytes)
    (out_path / "sig" / "manifest.sig").write_bytes(sign_fn(man_bytes))
    (out_path / "sig" / "publisher.pub").write_bytes(pub_bytes)

    print(f"PASS: Shard generated at {out_path}")
    print(f"  Entities: {len(entities)}")
    print(f"  Claims:   {len(claims)}")
    print(f"  Spans:    {len(unique_spans)}")
    print(f"  Suite:    {suite}")
    print(f"  Root:     {integrity_root[:24]}...")


@click.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.argument("out", type=click.Path(path_type=Path))
@click.option(
    "--suite",
    "suite_name",
    type=click.Choice([SUITE_MLDSA44, SUITE_ED25519]),
    default=SUITE_MLDSA44,
    show_default=True,
    help="Cryptographic suite.",
)
@click.option(
    "--legacy",
    is_flag=True,
    default=False,
    help=f"Alias for --suite {SUITE_ED25519}.",
)
@click.option(
    "--gold",
    is_flag=True,
    help="Use canonical test key and timestamp (for reproducible gold shards, ed25519 only).",
)
def main(capsule: Path, out: Path, suite_name: str, legacy: bool, gold: bool) -> None:
    """Compile a Capsule into a Shard."""
    effective_suite = SUITE_ED25519 if (legacy or suite_name == SUITE_ED25519) else SUITE_MLDSA44
    try:
        compile_capsule(
            capsule,
            out,
            signing_key=CANONICAL_TEST_KEY if gold else None,
            timestamp=GOLD_TIMESTAMP if gold else None,
            suite=effective_suite,
        )
    except Exception as e:
        print(f"FATAL: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
