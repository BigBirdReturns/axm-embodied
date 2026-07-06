"""Post-run compiler: frame-capture capsule -> Genesis v1 shard.

The camera-frame sibling of ``compile.py``, same two-step architecture:

  1. Parse capture events (triggers, windows, kept frames) into canonical
     candidates the Genesis kernel understands.
  2. Delegate ALL shard construction to ``axm_build.compiler_generic`` — the
     only path that produces a genesis-verifiable shard.

Sealed natively by the kernel compiler:

  - ``extra_content``: ``frames.bin`` (opaque sensor bytes, verbatim) and
    ``capture_manifest.json`` (the explicit ``physical_capture`` tier + limits)
    are copied into content/, listed in the manifest sources bijection, and
    hashed into the Merkle tree as raw bytes.
  - ``extra_ext``: FrameJudge's verified byte-level index is published as
    ``ext/streams@1.jsonl`` (the kernel's registered stream-index extension,
    with ``stream="frames"``). The continuity chain itself is sealed twice
    without needing an ext column: embedded in every ``frames.bin`` record
    (inside the Merkle tree) and verbatim in the ``frame_kept`` lines of the
    sealed source.

Profile note (deliberate): this capsule declares NO ``embodied@1`` profile.
That profile asserts the VLA hot-stream continuity check over
``cam_latents.bin``, which a camera capsule does not carry. Frame continuity
is enforced *before* sealing by :class:`~axm_embodied.frame_capture.FrameJudge`
(disk is truth — a broken chain never compiles) and pinned *after* sealing by
the chained records inside the Merkle-sealed ``frames.bin``. Claiming embodied@1
here would be a false profile assertion, so it is not made.

No trigger inference, no vision, no filtering: the compiler seals what the
sensor emitted and what the caller declared, nothing more.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import blake3

from axm_build.compiler_generic import CompilerConfig, compile_generic_shard

from axm_embodied.frame_capture import PHYSICAL_TIER, FrameJudge

_NAMESPACE = "embodied/capture"
_PUBLISHER_ID = "@axm_embodied"
_PUBLISHER_NAME = "AXM Embodied"


def _utc_now_rfc3339() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _derive_shard_id(shard_dir: Path) -> str:
    """shard_id = "sh1_" + hex(BLAKE3(manifest bytes)) — derived, never stored."""
    return "sh1_" + blake3.blake3((Path(shard_dir) / "manifest.json").read_bytes()).hexdigest()


def _extract_candidates(events_path: Path) -> list[dict]:
    """Capture events -> Genesis candidates. Claims state what the record IS
    (a trigger was declared, a frame's bytes hash to H, the tier is
    physical_capture) — never what the pixels mean."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def _add(subj: str, pred: str, obj: str, obj_type: str, tier: int, ev: str) -> None:
        key = f"{subj}\x00{pred}\x00{obj}\x00{obj_type}\x00{ev}"
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {"subject": subj, "predicate": pred, "object": obj,
             "object_type": obj_type, "tier": tier, "evidence": ev}
        )

    with open(events_path, "rb") as f:
        for line_bytes in f.read().split(b"\n"):
            if not line_bytes:
                continue
            text = line_bytes.decode("utf-8")
            evt = json.loads(text)
            sensor = evt.get("sensor_id", "sensor-unknown")

            if evt.get("evt") == "capture_trigger":
                # The trigger's reason/source are caller-declared facts about
                # the record, sealed verbatim.
                _add(sensor, "declared_trigger", str(evt.get("reason", "")),
                     "literal:string", 1, text)
                _add(f"trigger/frame-{evt['frame_id']}", "trigger_source",
                     str(evt.get("source", "")), "literal:string", 1, text)

            elif evt.get("evt") == "capture_window_opened":
                _add(sensor, "opened_capture_window",
                     f"frame-{evt.get('first_kept_frame_id', evt['frame_id'])}",
                     "literal:string", 1, text)

            elif evt.get("evt") == "capture_window_closed":
                _add(sensor, "closed_capture_window", f"frame-{evt['frame_id']}",
                     "literal:string", 1, text)

            elif evt.get("evt") == "frame_kept":
                _add(f"frame-{evt['frame_id']}", "content_sha256",
                     str(evt.get("content_sha256", "")), "literal:string", 1, text)

    return candidates


def compile_frame_capsule(
    capsule_path: Path | str,
    out_path: Path | str,
    secret_key: bytes,
    timestamp: Optional[str] = None,
) -> str:
    """Compile a frame-capture capsule into a genesis-verifiable shard.

    FrameJudge runs FIRST: every payload hash and the full continuity chain are
    recomputed from disk and cross-checked against the log. A tampered,
    truncated, or reordered capsule never reaches the kernel compiler.
    Returns the derived ``sh1_`` shard identity.
    """
    capsule_path = Path(capsule_path)
    out_path = Path(out_path)

    events_path = capsule_path / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"No events.jsonl in {capsule_path}")
    manifest_path = capsule_path / "capture_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No capture_manifest.json in {capsule_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("evidence_tier") != PHYSICAL_TIER:
        raise ValueError(
            f"capsule tier is {manifest.get('evidence_tier')!r}, not {PHYSICAL_TIER!r}; "
            f"this compiler seals physical captures only"
        )

    # Disk is truth: verify every hash + the whole chain BEFORE sealing.
    judge_records = FrameJudge(capsule_path).verify()
    streams_rows = FrameJudge.streams_rows(judge_records)

    candidates = _extract_candidates(events_path)
    if not candidates:
        raise ValueError(f"No candidates extracted from {events_path}")

    with tempfile.TemporaryDirectory(prefix="axm_frame_compile_") as tmp:
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
            created_at=timestamp or _utc_now_rfc3339(),
            title=f"Frame capture capsule {capsule_path.name}",
            license_spdx="Apache-2.0",
            profiles=(),  # deliberately NOT embodied@1 — see module docstring
            extra_content=(
                ("frames.bin", capsule_path / "frames.bin"),
                ("capture_manifest.json", manifest_path),
            ),
            extra_ext={"streams@1": streams_rows} if streams_rows else None,
        )

        ok = compile_generic_shard(cfg)
        if not ok:
            raise RuntimeError(
                "Genesis kernel rejected the shard (self-verification failed "
                "or no claims compiled)"
            )

    return _derive_shard_id(out_path)
