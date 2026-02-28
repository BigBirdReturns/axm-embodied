#!/usr/bin/env python3
"""
axm-embodied/src/axm_embodied/compile.py

Post-run compiler: capsule directory -> Genesis shard.

Architecture
------------
This file does exactly two things:

  1. Parse embodied-specific data (events.jsonl, Mens Rea, wheel_slip events)
     into a canonical candidates.jsonl that the Genesis compiler understands.

  2. Delegate all shard construction to axm_build.compiler_generic — the only
     path that produces a genesis-verifiable shard (correct manifest schema,
     Parquet schemas, Merkle tree, signing, and self-verification).

Two-pass compilation for cam_latents.bin
-----------------------------------------
compile_generic_shard does not support extra content files (it manages
content/ itself). cam_latents.bin must be in content/ to become a Merkle
leaf that triggers REQ 5 continuity checks. We handle this with a
deterministic two-pass approach:

  Pass 1: compile events.jsonl -> valid shard (PASS without latents)
  Inject: copy cam_latents.bin into content/
  Pass 2: recompute Merkle root (public API: compute_merkle_root)
          rewrite manifest with new root, re-sign with same key

Both passes use the same key material. The final shard contains
cam_latents.bin as a Merkle leaf, and axm-verify REQ 5 will check it.

Usage
-----
    axm-compile <capsule_dir> <out_dir>
    axm-compile <capsule_dir> <out_dir> --suite ed25519
    axm-compile <capsule_dir> <out_dir> --gold

Dependency chain
----------------
    sim_robot_final.py  ->  capsule/
    compile.py          ->  shard/           (this file)
    axm_embodied.streams                     (ext/streams@1.parquet)
    axm_build.compiler_generic               (canonical shard compilation)
    axm_build.merkle.compute_merkle_root     (re-seal after latent injection)
    axm_verify.logic                         (self-verification gate)
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import click

# Genesis compiler: the only path to a verifiable shard
from axm_build.compiler_generic import CompilerConfig, compile_generic_shard
from axm_build.manifest import dumps_canonical_json
from axm_build.merkle import compute_merkle_root
from axm_build.sign import (
    SUITE_ED25519,
    SUITE_MLDSA44,
    mldsa44_keygen,
    mldsa44_sign,
    signing_key_from_private_key_bytes,
)
from axm_verify.logic import verify_shard as _verify_shard

# Binary stream evidence: embodied-specific, stays local
from axm_embodied.streams import compile_streams_evidence

# Canonical demo key (Ed25519, matches governance/trust_store.json)
_CANONICAL_PUBLISHER_SEED = bytes.fromhex(
    "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"
)
GOLD_TIMESTAMP = "2026-01-01T00:00:00Z"

_NAMESPACE    = "embodied/wheel_slip"
_PUBLISHER_ID = "@axm_embodied"
_PUBLISHER_NAME = "AXM Embodied"


# ---------------------------------------------------------------------------
# Step 1: Extract embodied events -> candidates
# ---------------------------------------------------------------------------

def _extract_candidates(events_path: Path) -> list[dict]:
    """Parse events.jsonl into Genesis-compatible candidates.

    Each candidate:  subject, predicate, object, object_type, tier, evidence

    evidence must appear exactly once in the source text.
    compile_generic_shard enforces this — ambiguous spans are compile errors.
    """
    with open(events_path, "rb") as f:
        raw_bytes = f.read()

    candidates: list[dict] = []
    seen: set[str] = set()

    def _add(subj: str, pred: str, obj: str, obj_type: str, tier: int, ev: str) -> None:
        if ev in seen:
            return
        seen.add(ev)
        candidates.append({
            "subject": subj, "predicate": pred, "object": obj,
            "object_type": obj_type, "tier": tier, "evidence": ev,
        })

    for line_bytes in raw_bytes.split(b"\n"):
        if not line_bytes:
            continue
        text = line_bytes.decode("utf-8")
        evt = json.loads(text)

        if evt.get("evt") == "wheel_slip":
            robot = evt.get("robot_id", "robot-001")
            _add(robot, "observed", "wheel_slip", "entity", 2, text)
            _add("wheel_slip", "on_surface", evt["surface"], "literal:string", 2, text)

        elif evt.get("evt") == "recovery_action":
            _add("wheel_slip", "resolved_by", evt["action"], "entity", 1, text)
            _add(evt["action"], "applied_value", str(evt["value"]),
                 "literal:string", 2, text)

        elif evt.get("evt") == "emergency_stop":
            robot = evt.get("robot_id", "robot-001")
            _add(robot, "triggered", "emergency_stop", "entity", 1, text)

        # Mens Rea: action distribution on every frame
        if "selected_action" in evt and "action_distribution" in evt:
            robot = evt.get("robot_id", "robot-001")
            _add(robot, "selected_action", evt["selected_action"], "entity", 1, text)
            for action, conf in evt["action_distribution"].items():
                lit = json.dumps({"action": action, "confidence": conf},
                                 separators=(",", ":"))
                _add(robot, "considered_action", lit, "literal:string", 2, text)

    return candidates


# ---------------------------------------------------------------------------
# Inject cam_latents.bin and re-seal the shard (pass 2)
# ---------------------------------------------------------------------------

def _inject_latents_and_reseal(
    out_path: Path,
    lat_src: Path,
    suite: str,
    sk_bytes: bytes,   # raw signing key (32 B for Ed25519, 2528 B for ML-DSA-44)
    pk_bytes: bytes,   # public key bytes (already written to sig/publisher.pub)
) -> None:
    """Copy cam_latents.bin into content/, recompute Merkle root, re-sign manifest.

    After this call the shard includes cam_latents.bin as a proper Merkle leaf.
    axm-verify REQ 5 will check frame continuity against it.
    """
    shutil.copy2(lat_src, out_path / "content" / "cam_latents.bin")

    # Recompute root over all files including the new latent file
    new_root = compute_merkle_root(out_path, suite=suite)

    # Rewrite manifest with updated Merkle root
    manifest = json.loads((out_path / "manifest.json").read_bytes())
    manifest["integrity"]["merkle_root"] = new_root
    manifest["shard_id"] = f"shard_blake3_{new_root}"

    man_bytes = dumps_canonical_json(manifest)
    (out_path / "manifest.json").write_bytes(man_bytes)

    # Re-sign manifest
    if suite == SUITE_MLDSA44:
        sig = mldsa44_sign(sk_bytes, man_bytes)
    else:
        from nacl.signing import SigningKey
        nacl_sk = SigningKey(sk_bytes)
        sig = nacl_sk.sign(man_bytes).signature

    (out_path / "sig" / "manifest.sig").write_bytes(sig)

    # Verify the resealed shard
    result = _verify_shard(out_path, trusted_key_path=out_path / "sig" / "publisher.pub")
    if result["status"] != "PASS":
        raise RuntimeError(
            f"Shard failed verification after latent injection: {result['errors']}"
        )


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

def compile_capsule(
    capsule_path: Path,
    out_path: Path,
    signing_key: bytes | None = None,
    timestamp: str | None = None,
    suite: str = SUITE_MLDSA44,
) -> None:
    """Compile a capsule directory into a genesis-verifiable shard.

    Output passes:  axm-verify shard <out_path>
    """
    print(f"Compiling capsule: {capsule_path}")
    print(f"  Suite: {suite}")

    events_path = capsule_path / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"No events.jsonl in {capsule_path}")

    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # Build key material
    if suite == SUITE_MLDSA44:
        kp = mldsa44_keygen()
        sk_raw = kp.secret_key            # 2528 B
        pk_raw = kp.public_key            # 1312 B
        private_key_for_cfg = sk_raw + pk_raw  # 3840 B — what CompilerConfig expects
    else:
        nacl_sk = signing_key_from_private_key_bytes(signing_key or _CANONICAL_PUBLISHER_SEED)
        sk_raw = bytes(nacl_sk)           # 32 B
        pk_raw = bytes(nacl_sk.verify_key)
        private_key_for_cfg = sk_raw

    work_dir = Path(tempfile.mkdtemp(prefix="axm_compile_"))
    try:
        source_path = work_dir / "source.txt"
        shutil.copy2(events_path, source_path)

        candidates = _extract_candidates(events_path)
        if not candidates:
            raise ValueError(f"No candidates extracted from {events_path}")

        candidates_path = work_dir / "candidates.jsonl"
        with candidates_path.open("w") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # ── Pass 1: compile via genesis (correct manifest + parquet + signing) ──
        cfg = CompilerConfig(
            source_path=source_path,
            candidates_path=candidates_path,
            out_dir=out_path,
            private_key=private_key_for_cfg,
            publisher_id=_PUBLISHER_ID,
            publisher_name=_PUBLISHER_NAME,
            namespace=_NAMESPACE,
            created_at=timestamp,
            suite=suite,
        )

        ok = compile_generic_shard(cfg)
        if not ok:
            raise RuntimeError("compile_generic_shard returned False (no claims compiled)")

        # ── Pass 2: inject cam_latents.bin and reseal ────────────────────────
        lat_src = capsule_path / "cam_latents.bin"
        if lat_src.exists():
            _inject_latents_and_reseal(out_path, lat_src, suite, sk_raw, pk_raw)
            print(f"  Latents: content/cam_latents.bin sealed in Merkle tree")

        # ── Write binary stream evidence (ext/ — domain extension) ──────────
        if lat_src.exists():
            compile_streams_evidence(capsule_path, out_path)
            print(f"  Streams: ext/streams@1.parquet written")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    manifest = json.loads((out_path / "manifest.json").read_bytes())
    stats   = manifest.get("statistics", {})
    merkle  = manifest.get("integrity", {}).get("merkle_root", "?")

    print(f"PASS: Shard written to {out_path}")
    print(f"  Entities: {stats.get('entities', 0)}")
    print(f"  Claims:   {stats.get('claims', 0)}")
    print(f"  Suite:    {manifest.get('suite', suite)}")
    print(f"  Merkle:   {merkle[:32]}...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.argument("out",     type=click.Path(path_type=Path))
@click.option(
    "--suite", "suite_name",
    type=click.Choice([SUITE_MLDSA44, SUITE_ED25519]),
    default=SUITE_MLDSA44, show_default=True,
    help="Cryptographic suite.",
)
@click.option("--legacy", is_flag=True, default=False,
              help=f"Alias for --suite {SUITE_ED25519}.")
@click.option("--gold", is_flag=True,
              help="Use canonical test key + timestamp (reproducible gold shards, ed25519).")
def main(capsule: Path, out: Path, suite_name: str, legacy: bool, gold: bool) -> None:
    """Compile a capsule directory into a Genesis shard.

    Output passes axm-verify shard with a clean PASS.
    """
    effective_suite = (
        SUITE_ED25519 if (legacy or suite_name == SUITE_ED25519) else SUITE_MLDSA44
    )
    try:
        compile_capsule(
            capsule, out,
            signing_key=_CANONICAL_PUBLISHER_SEED if gold else None,
            timestamp=GOLD_TIMESTAMP if gold else None,
            suite=effective_suite,
        )
    except Exception as e:
        print(f"FATAL: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
