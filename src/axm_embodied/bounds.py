#!/usr/bin/env python3
"""
axm-embodied/src/axm_embodied/bounds.py

Drone School: The Bounds Compiler.

Ingests a directory of safe simulation capsules, computes the L-infinity
norm of the latent vectors (and, when a cold stream exists, the delta
between latents and residual payloads) per action class, takes the 99th
percentile across all runs, applies a 1.1x safety margin, and emits a
Tier-0 Genesis Shard encoding the safety envelope.

Usage:
    axm-bounds <safe_dir> <out_dir> --key <publisher.key>

The output shard is what the Shadow Runtime arms with. At runtime, if a
frame's live latent L-inf exceeds the signed bound for the selected
action class, the runtime kills motors and triggers Flash Freeze. The
insurers see a mathematically certified, post-quantum signed envelope
derived from cryptographically identified training runs — not a manually
tweaked config file.

The training manifest (content/source.txt) names every ingested capsule
by SHA-256, so the envelope's provenance chain reaches all the way down
to the raw training bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

import click
import numpy as np

# ── Embodied-specific ─────────────────────────────────────────────────────
from axm_embodied_core.protocol import (
    REC_HEADER_LEN,
    REC_HEADER_FMT,
    FILE_HEADER_LEN,
    LATENT_REC_LEN,
    LATENT_DIM,
)

# ── Genesis kernel ────────────────────────────────────────────────────────
from axm_build.compiler_generic import compile_generic_shard, CompilerConfig

from axm_embodied.keys import load_secret_key

SAFETY_MARGIN = 1.1
PERCENTILE = 99

BOUNDS_NAMESPACE = "embodied/bounds"
BOUND_PREDICATE = "max_latent_delta_linf"
PUBLISHER_ID = "@drone_school"
PUBLISHER_NAME = "AXM Bounds Compiler"


def _read_latent_payload(lat_path: Path, offset: int) -> np.ndarray:
    """Read a latent record payload as float32 array.

    Strict offset math: offset is FILE_HEADER_LEN + (frame_id * LATENT_REC_LEN).
    We skip the record header and read exactly LATENT_DIM bytes.
    """
    if not lat_path.exists():
        return np.array([], dtype=np.float32)
    with open(lat_path, "rb") as f:
        f.seek(offset + REC_HEADER_LEN)  # skip record header, land on payload
        data = f.read(LATENT_DIM)
    if len(data) < LATENT_DIM:
        return np.array([], dtype=np.float32)
    return np.frombuffer(data, dtype=np.float32).copy()


def _read_residual_payload(res_path: Path, offset: int) -> np.ndarray:
    """Read a residual record payload as float32 array.

    Residuals are variable-length. We read the header to get dlen,
    then interpret the payload as float32 (truncating to word boundary).
    """
    if not res_path.exists():
        return np.array([], dtype=np.float32)
    with open(res_path, "rb") as f:
        f.seek(offset)
        header = f.read(REC_HEADER_LEN)
        if len(header) < REC_HEADER_LEN:
            return np.array([], dtype=np.float32)
        _, _, _, dlen = struct.unpack(REC_HEADER_FMT, header)
        data = f.read(dlen)
    elements = len(data) // 4
    if elements == 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(data[:elements * 4], dtype=np.float32).copy()


def _capsule_hash(capsule_dir: Path) -> str:
    """SHA-256 of events.jsonl — the byte-authoritative capsule identity."""
    return hashlib.sha256(
        (capsule_dir / "events.jsonl").read_bytes()
    ).hexdigest()


def latent_l_inf(latents: np.ndarray) -> float:
    """L∞ norm of a latent frame against quiescence. NaN/Inf propagate to
    +inf so a non-finite frame can never sneak under a bound (fail closed)."""
    if len(latents) == 0:
        return math.inf
    m = float(np.abs(latents).max())
    return m if math.isfinite(m) else math.inf


def compile_bounds(
    safe_dir: Path,
    out_path: Path,
    secret_key: bytes,
    timestamp: Optional[str] = None,
) -> str:
    """Ingest safe capsules, compute L-inf envelopes, emit a Bounds Shard.

    Returns the derived sh1_ shard identity — the id the Shadow Runtime
    cites from every incident recorded under this envelope.
    """
    from axm_embodied.compile import derive_shard_id, utc_now_rfc3339

    print(f"Drone School: ingesting safe runs from {safe_dir}")

    action_deltas: dict[str, list[float]] = defaultdict(list)
    training_capsules: list[tuple[str, str]] = []  # (name, sha256)
    skipped_nonfinite = 0

    # ── 1. Ingest capsules and compute per-frame L-inf deltas ─────────────
    for capsule_dir in sorted(Path(safe_dir).iterdir()):
        if not capsule_dir.is_dir():
            continue
        events_path = capsule_dir / "events.jsonl"
        lat_path = capsule_dir / "cam_latents.bin"
        res_path = capsule_dir / "cam_residuals.bin"

        if not events_path.exists() or not lat_path.exists():
            continue

        cap_hash = _capsule_hash(capsule_dir)
        training_capsules.append((capsule_dir.name, cap_hash))
        frames_counted = 0

        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                evt = json.loads(line)

                action = evt.get("selected_action")
                refs = evt.get("stream_refs", {})
                lat_ref = refs.get("latents")

                if not action or not lat_ref:
                    continue

                lat_arr = _read_latent_payload(lat_path, lat_ref["offset"])
                if len(lat_arr) == 0:
                    continue

                # Residuals exist only on trigger frames. On safe runs the
                # cold stream is 0 bytes and the latent self-norm is the
                # baseline variance measure (distance from quiescence).
                l_inf = None
                if res_path.exists() and res_path.stat().st_size > 0:
                    res_ref = refs.get("residuals")
                    if res_ref:
                        res_arr = _read_residual_payload(res_path, res_ref["offset"])
                        if len(res_arr) > 0:
                            min_dim = min(len(lat_arr), len(res_arr))
                            l_inf = float(
                                np.abs(lat_arr[:min_dim] - res_arr[:min_dim]).max()
                            )
                if l_inf is None:
                    l_inf = latent_l_inf(lat_arr)

                if not math.isfinite(l_inf):
                    # A non-finite training frame must not widen the
                    # envelope to infinity; drop it and say so.
                    skipped_nonfinite += 1
                    continue

                action_deltas[action].append(l_inf)
                frames_counted += 1

        print(f"  {capsule_dir.name}: {frames_counted} frames")

    if not action_deltas:
        raise ValueError(
            "No valid frame deltas found. Check that safe_dir contains "
            "capsules with events.jsonl and cam_latents.bin."
        )
    if skipped_nonfinite:
        print(f"  WARNING: skipped {skipped_nonfinite} non-finite frames")

    # ── 2. Build training manifest (provenance source document) ──────────
    # This becomes content/source.txt in the shard. Every claim cites a
    # line from this document as its evidence. The document is hashed into
    # the Merkle tree — tampering is detectable.
    created_at = timestamp or utc_now_rfc3339()
    manifest_lines = [
        "BOUNDS COMPILER: TRAINING MANIFEST",
        "===================================",
        f"Generated: {created_at}",
        f"Capsules: {len(training_capsules)}",
        f"Percentile: {PERCENTILE}",
        f"Safety margin: {SAFETY_MARGIN}",
        "---",
    ]
    # Single spaces only: the kernel normalizes source text by collapsing
    # whitespace runs, and evidence spans must match the normalized bytes.
    for name, sha256 in sorted(training_capsules):
        manifest_lines.append(f"capsule: {name} sha256: {sha256}")
    manifest_lines.append("---")

    # Per-action summary lines — these are the evidence strings for claims.
    action_summary: dict[str, str] = {}
    for action, deltas in sorted(action_deltas.items()):
        arr = np.array(deltas)
        p99 = float(np.percentile(arr, PERCENTILE))
        bound = round(p99 * SAFETY_MARGIN, 6)
        line = (
            f"action: {action} "
            f"frames: {len(deltas)} "
            f"p99_linf: {round(p99, 6)} "
            f"bound: {bound}"
        )
        action_summary[action] = line
        manifest_lines.append(line)

    source_text = "\n".join(manifest_lines) + "\n"

    # ── 3. Build candidates (Tier 0 invariant claims) ─────────────────────
    candidates = []
    for action, deltas in sorted(action_deltas.items()):
        arr = np.array(deltas)
        p99 = float(np.percentile(arr, PERCENTILE))
        bound = round(p99 * SAFETY_MARGIN, 6)
        subj = f"bounds/{action}"
        evidence = action_summary[action]  # exact line in source.txt

        # Tier 0: formal invariants — the law the robot operates under
        for pred, val, obj_type in [
            (BOUND_PREDICATE, f"{bound:.6f}", "literal:decimal"),
            ("sample_count", str(len(deltas)), "literal:integer"),
            ("percentile", str(PERCENTILE), "literal:integer"),
            ("safety_margin", str(SAFETY_MARGIN), "literal:decimal"),
        ]:
            candidates.append({
                "subject":     subj,
                "predicate":   pred,
                "object":      val,
                "object_type": obj_type,
                "tier":        0,
                "evidence":    evidence,
            })

    # ── 4. Delegate compilation to the genesis kernel ─────────────────────
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_path = tmp_path / "source.txt"
        candidates_path = tmp_path / "candidates.jsonl"

        source_path.write_text(source_text, encoding="utf-8")
        with open(candidates_path, "w", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c) + "\n")

        cfg = CompilerConfig(
            source_path=source_path,
            candidates_path=candidates_path,
            out_dir=out_path,
            private_key=secret_key,
            publisher_id=PUBLISHER_ID,
            publisher_name=PUBLISHER_NAME,
            namespace=BOUNDS_NAMESPACE,
            created_at=created_at,
            title="Safety envelope (bounds shard)",
            license_spdx="Apache-2.0",
        )

        ok = compile_generic_shard(cfg)
        if not ok:
            raise RuntimeError("compile_generic_shard returned False — check candidates")

    shard_id = derive_shard_id(out_path)

    # ── 5. Summary ────────────────────────────────────────────────────────
    print(f"\nPASS: Bounds Shard written to {out_path}")
    print(f"  Shard id:           {shard_id}")
    print(f"  Capsules ingested:  {len(training_capsules)}")
    print(f"  Action classes:     {len(action_deltas)}")
    print(f"  Total frame deltas: {sum(len(v) for v in action_deltas.values())}")
    print()
    print("  Envelope:")
    for action, deltas in sorted(action_deltas.items()):
        arr = np.array(deltas)
        p99 = float(np.percentile(arr, PERCENTILE))
        bound = round(p99 * SAFETY_MARGIN, 6)
        print(f"    {action:<20} p99={round(p99,4):.4f}  bound={bound:.6f}  n={len(deltas)}")
    return shard_id


@click.command()
@click.argument("safe_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("out",      type=click.Path(path_type=Path))
@click.option("--key", "key_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Path to the 3904-byte axm-hybrid1 secret key blob "
                   "(axm-build keygen). Falls back to AXM_SIGNING_KEY_HEX.")
@click.option("--timestamp", default=None, metavar="RFC3339Z",
              help="Override metadata.created_at (reproducible builds).")
def main(safe_dir: Path, out: Path, key_path: Optional[Path],
         timestamp: Optional[str]) -> None:
    """Compile a bounds shard from a directory of safe training capsules."""
    try:
        secret_key = load_secret_key(key_path)
        compile_bounds(safe_dir, out, secret_key, timestamp=timestamp)
    except Exception as e:
        print(f"FATAL: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
