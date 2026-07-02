#!/usr/bin/env python3
"""
axm-embodied/src/axm_embodied/compile.py

Post-run compiler: capsule directory -> Genesis v1 shard.

Architecture
------------
This file does exactly two things:

  1. Parse embodied-specific data (events.jsonl, Mens Rea, safety events)
     into a canonical candidates.jsonl the Genesis kernel understands.

  2. Delegate all shard construction to axm_build.compiler_generic — the
     only path that produces a genesis-verifiable shard (canonical JSONL
     tables, Merkle tree, axm-hybrid1 signing, self-verification).

The kernel compiler seals the binary streams natively:

  - ``extra_content``: cam_latents.bin (and cam_residuals.bin when the
    cold stream flushed) are copied into content/, listed in the manifest
    sources bijection, and hashed into the Merkle tree as raw bytes.
  - ``profiles=("embodied@1",)``: the shard declares the non-selective
    recording profile, so every conforming verifier runs the hot-stream
    continuity check (E_BUFFER_DISCONTINUITY on any frame gap).
  - ``extra_ext``: StrictJudge's byte-level stream index is published as
    ext/streams@1.jsonl (spec/profiles/embodied@1.md section 7).

Incident lineage
----------------
When a capsule was recorded under an armed Shadow Runtime, pass the
safety envelope's shard id as ``envelope_shard_id``: breach claims then
carry an ext/references@1 row citing the exact signed envelope that was
in force at the moment the motors were killed.

Keys
----
There is no default signing key: a signature made with a published key
proves integrity, never authenticity. Generate a keypair with
``axm-build keygen`` and pass the 3904-byte secret key blob.

Usage
-----
    axm-compile <capsule_dir> <out_dir> --key <publisher.key>
    axm-compile <capsule_dir> <out_dir> --key <publisher.key> \
        --cites sh1_<envelope shard id>
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import blake3
import click

# Genesis kernel: the only path to a verifiable shard
from axm_build.compiler_generic import CompilerConfig, compile_generic_shard

# Binary stream evidence: embodied-specific, stays local
from axm_embodied.keys import load_secret_key
from axm_embodied.streams import build_streams_evidence

PROFILE_EMBODIED_V1 = "embodied@1"

_NAMESPACE = "embodied/incident"
_PUBLISHER_ID = "@axm_embodied"
_PUBLISHER_NAME = "AXM Embodied"


def utc_now_rfc3339() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def derive_shard_id(shard_dir: Path) -> str:
    """shard_id = "sh1_" + hex(BLAKE3(manifest bytes)) — derived, never stored."""
    manifest_bytes = (Path(shard_dir) / "manifest.json").read_bytes()
    return "sh1_" + blake3.blake3(manifest_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Step 1: Extract embodied events -> candidates
# ---------------------------------------------------------------------------

def _extract_candidates(
    events_path: Path,
    envelope_shard_id: Optional[str] = None,
) -> list[dict]:
    """Parse events.jsonl into Genesis-compatible candidates.

    Each candidate:  subject, predicate, object, object_type, tier, evidence

    evidence must appear exactly once in the source text.
    compile_generic_shard enforces this — ambiguous spans are compile errors.
    """
    with open(events_path, "rb") as f:
        raw_bytes = f.read()

    candidates: list[dict] = []
    seen: set[str] = set()

    envelope_ref = None
    if envelope_shard_id:
        envelope_ref = [{
            "dst_shard_id": envelope_shard_id,
            "relation_type": "cites",
            "dst_object_type": "shard",
            "dst_object_id": "",
            "confidence": "1.0",
            "note": "safety envelope in force at the moment of the breach",
        }]

    def _add(subj: str, pred: str, obj: str, obj_type: str, tier: int, ev: str,
             references: Optional[list] = None) -> None:
        # Dedupe exact duplicate candidates; multiple DIFFERENT claims may
        # cite the same event line (the kernel dedupes rows by primary key).
        key = f"{subj}\x00{pred}\x00{obj}\x00{obj_type}\x00{ev}"
        if key in seen:
            return
        seen.add(key)
        cand = {
            "subject": subj, "predicate": pred, "object": obj,
            "object_type": obj_type, "tier": tier, "evidence": ev,
        }
        if references:
            cand["references"] = references
        candidates.append(cand)

    for line_bytes in raw_bytes.split(b"\n"):
        if not line_bytes:
            continue
        text = line_bytes.decode("utf-8")
        evt = json.loads(text)
        robot = evt.get("robot_id", "robot-001")

        if evt.get("evt") == "wheel_slip":
            _add(robot, "observed", "wheel_slip", "entity", 2, text)
            if "surface" in evt:
                _add("wheel_slip", "on_surface", evt["surface"], "literal:string", 2, text)

        elif evt.get("evt") == "recovery_action":
            _add("wheel_slip", "resolved_by", evt["action"], "entity", 1, text)
            _add(evt["action"], "applied_value", str(evt["value"]),
                 "literal:string", 2, text)

        elif evt.get("evt") == "emergency_stop":
            _add(robot, "triggered", "emergency_stop", "entity", 1, text)

        elif evt.get("evt") == "envelope_breach":
            # Actus Reus of the Shadow Runtime: physics left the signed
            # envelope. These claims cite the envelope shard (references@1)
            # so the incident is cryptographically linked to the exact law
            # it broke.
            _add(robot, "breached_envelope", str(evt.get("action", "")),
                 "literal:string", 1, text, references=envelope_ref)
            if isinstance(evt.get("l_inf"), (int, float)):
                _add(f"breach/frame-{evt['frame_id']}", "observed_l_inf",
                     str(evt["l_inf"]), "literal:decimal", 1, text)
            if isinstance(evt.get("bound"), (int, float)):
                _add(f"breach/frame-{evt['frame_id']}", "envelope_bound",
                     str(evt["bound"]), "literal:decimal", 1, text)

        # Mens Rea: action distribution on every frame
        if "selected_action" in evt and "action_distribution" in evt:
            _add(robot, "selected_action", evt["selected_action"], "entity", 1, text)
            for action, conf in evt["action_distribution"].items():
                lit = json.dumps({"action": action, "confidence": conf},
                                 separators=(",", ":"))
                _add(robot, "considered_action", lit, "literal:string", 2, text)

    return candidates


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

def compile_capsule(
    capsule_path: Path,
    out_path: Path,
    secret_key: bytes,
    timestamp: Optional[str] = None,
    envelope_shard_id: Optional[str] = None,
) -> str:
    """Compile a capsule directory into a genesis-verifiable shard.

    Returns the derived sh1_ shard identity. The kernel compiler
    self-verifies: it will not return success for a shard that fails
    axm-verify (including the embodied@1 continuity check).
    """
    capsule_path = Path(capsule_path)
    out_path = Path(out_path)
    print(f"Compiling capsule: {capsule_path}")

    events_path = capsule_path / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"No events.jsonl in {capsule_path}")

    candidates = _extract_candidates(events_path, envelope_shard_id)
    if not candidates:
        raise ValueError(f"No candidates extracted from {events_path}")

    # StrictJudge: verify binary streams BEFORE sealing anything. Disk is
    # truth — a capsule whose log disagrees with its bytes never compiles.
    lat_src = capsule_path / "cam_latents.bin"
    streams_rows = build_streams_evidence(capsule_path) if lat_src.exists() else []

    extra_content: list[tuple[str, Path]] = []
    if lat_src.exists():
        extra_content.append(("cam_latents.bin", lat_src))
    res_src = capsule_path / "cam_residuals.bin"
    if res_src.exists() and res_src.stat().st_size > 0:
        extra_content.append(("cam_residuals.bin", res_src))

    with tempfile.TemporaryDirectory(prefix="axm_compile_") as tmp:
        candidates_path = Path(tmp) / "candidates.jsonl"
        with candidates_path.open("w", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        cfg = CompilerConfig(
            source_path=events_path,
            candidates_path=candidates_path,
            out_dir=out_path,
            private_key=secret_key,
            publisher_id=_PUBLISHER_ID,
            publisher_name=_PUBLISHER_NAME,
            namespace=_NAMESPACE,
            created_at=timestamp or utc_now_rfc3339(),
            title=f"Flash Freeze capsule {capsule_path.name}",
            license_spdx="Apache-2.0",
            profiles=(PROFILE_EMBODIED_V1,),
            extra_content=tuple(extra_content),
            extra_ext={"streams@1": streams_rows} if streams_rows else None,
        )

        ok = compile_generic_shard(cfg)
        if not ok:
            raise RuntimeError(
                "Genesis kernel rejected the shard (self-verification failed "
                "or no claims compiled)"
            )

    shard_id = derive_shard_id(out_path)
    manifest = json.loads((out_path / "manifest.json").read_bytes())
    stats = manifest.get("statistics", {})

    print(f"PASS: Shard written to {out_path}")
    print(f"  Shard id: {shard_id}")
    print(f"  Entities: {stats.get('entities', 0)}")
    print(f"  Claims:   {stats.get('claims', 0)}")
    print(f"  Suite:    {manifest.get('suite')}")
    print(f"  Profiles: {', '.join(manifest.get('profiles', []))}")
    if streams_rows:
        print(f"  Streams:  ext/streams@1.jsonl ({len(streams_rows)} records)")
    if envelope_shard_id:
        print(f"  Cites:    {envelope_shard_id}")
    return shard_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.argument("out", type=click.Path(path_type=Path))
@click.option("--key", "key_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Path to the 3904-byte axm-hybrid1 secret key blob "
                   "(axm-build keygen). Falls back to AXM_SIGNING_KEY_HEX.")
@click.option("--cites", "envelope_shard_id", default=None, metavar="SH1_ID",
              help="Safety envelope shard id this incident was recorded under; "
                   "breach claims will cite it via ext/references@1.")
@click.option("--timestamp", default=None, metavar="RFC3339Z",
              help="Override metadata.created_at (reproducible builds).")
def main(capsule: Path, out: Path, key_path: Optional[Path],
         envelope_shard_id: Optional[str], timestamp: Optional[str]) -> None:
    """Compile a capsule directory into a Genesis shard.

    Output passes `axm-verify shard` with the embodied@1 profile checked.
    """
    try:
        secret_key = load_secret_key(key_path)
        compile_capsule(
            capsule, out, secret_key,
            timestamp=timestamp,
            envelope_shard_id=envelope_shard_id,
        )
    except Exception as e:
        print(f"FATAL: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
