"""Flash Freeze flight recorder — library form.

Extracted from the original simulator so the recorder can sit inside a
real perception→actuation loop (the Shadow Runtime) instead of only
inside a demo script. The on-disk format is frozen by the genesis
profile document `spec/profiles/embodied@1.md`:

- Hot stream  (``cam_latents.bin``):  AXLF file header, then gap-free
  AXLR records, one per frame, fsync'd before the frame is acknowledged.
  ``axm-verify`` rejects any capsule whose compiled shard has a frame gap
  (``E_BUFFER_DISCONTINUITY``) — you cannot selectively omit failures.
- Cold stream (``cam_residuals.bin``): AXRR records held in a pre-window
  ring buffer, flushed to disk only when :meth:`CapsuleRecorder.trigger`
  fires (Tier-1 safety event), then recorded for a post-window.
- Event log   (``events.jsonl``):     narrative. Disk is truth; the log's
  stream offsets are advisory and re-verified by StrictJudge at compile
  time.
"""
from __future__ import annotations

import json
import os
import struct
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from axm_embodied_core.protocol import (
    LATENT_DIM,
    LATENT_REC_LEN,
    MAGIC_LATENT_FILE,
    MAGIC_LATENT_REC,
    MAGIC_RESID_REC,
    REC_HEADER_FMT,
    VERSION,
)


def _fdatasync(fileobj) -> None:
    fileobj.flush()
    if hasattr(os, "fdatasync"):
        os.fdatasync(fileobj.fileno())
    else:  # pragma: no cover — non-POSIX fallback
        os.fsync(fileobj.fileno())


@dataclass(frozen=True)
class RecorderConfig:
    """Ring-buffer windows in frames; fsync policy for the hot stream."""
    pre_window_frames: int = 20    # history flushed when a trigger fires
    post_window_frames: int = 20   # future frames recorded after a trigger
    fsync_every_frame: bool = True


@dataclass
class FrameRef:
    """Where a frame's hot-stream record landed (strict offset math)."""
    frame_id: int
    offset: int
    length: int = LATENT_REC_LEN


class ResidualBuffer:
    """Cold-stream ring buffer: buffer until triggered, then write through.

    Pre-window history is flushed on trigger; the following
    ``post_window_frames`` records are written directly and committed with
    fdatasync when the window closes.
    """

    def __init__(self, file_handle, pre_window: int, post_window: int):
        self.f = file_handle
        self.buffer: deque[bytes] = deque(maxlen=pre_window)
        self.post_window = post_window
        self.recording_frames_left = 0

    def push(self, frame_id: int, data: bytes) -> str:
        header = struct.pack(REC_HEADER_FMT, MAGIC_RESID_REC, VERSION, frame_id, len(data))
        blob = header + data
        if self.recording_frames_left > 0:
            self.f.write(blob)
            self.recording_frames_left -= 1
            if self.recording_frames_left == 0:
                _fdatasync(self.f)  # durability: commit the event
            return "WRITTEN"
        self.buffer.append(blob)
        return "BUFFERED"

    def trigger(self) -> None:
        if self.recording_frames_left > 0:
            return  # already triggered
        while self.buffer:
            self.f.write(self.buffer.popleft())
        _fdatasync(self.f)  # durability: commit history
        self.recording_frames_left = self.post_window


class CapsuleRecorder:
    """Records one session capsule: hot stream, cold stream, event log.

    Usage::

        with CapsuleRecorder(out_dir, robot_id="unit-7") as rec:
            for latents, action, dist, residual in frames:
                rec.record_frame(latents, action, dist, residual=residual)
                if something_bad:
                    rec.trigger()
        capsule_path = rec.path
    """

    def __init__(
        self,
        out_dir: Path | str,
        robot_id: str,
        session_id: Optional[str] = None,
        config: RecorderConfig = RecorderConfig(),
    ):
        self.robot_id = robot_id
        self.session_id = session_id or str(uuid.uuid4())
        self.config = config
        self.path = Path(out_dir) / f"capsule-{self.session_id[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)

        self._f_lat = open(self.path / "cam_latents.bin", "wb", buffering=0)
        self._f_res = open(self.path / "cam_residuals.bin", "wb")
        self._f_log = open(self.path / "events.jsonl", "wb")
        self._f_lat.write(MAGIC_LATENT_FILE)  # file-level magic (safety)

        self._residuals = ResidualBuffer(
            self._f_res, config.pre_window_frames, config.post_window_frames
        )
        self._next_frame_id = 0
        self._triggered = False
        self._closed = False
        self._started_at = datetime.now(timezone.utc)

    # ── Recording ────────────────────────────────────────────────────────

    def record_frame(
        self,
        latents: bytes,
        selected_action: str,
        action_distribution: Dict[str, float],
        residual: Optional[bytes] = None,
        event: Optional[Dict[str, Any]] = None,
    ) -> FrameRef:
        """Record one frame. The hot stream is append-only and gap-free.

        ``latents`` must be exactly ``LATENT_DIM`` bytes — the profile
        freezes the record layout, and a short write would poison strict
        offset math for every later frame.
        """
        if self._closed:
            raise RuntimeError("CapsuleRecorder is closed")
        if len(latents) != LATENT_DIM:
            raise ValueError(
                f"latent payload must be exactly {LATENT_DIM} bytes, got {len(latents)}"
            )

        frame_id = self._next_frame_id
        self._next_frame_id += 1

        # Hot stream: strict offset captured BEFORE the write.
        lat_offset = self._f_lat.tell()
        header = struct.pack(REC_HEADER_FMT, MAGIC_LATENT_REC, VERSION, frame_id, len(latents))
        self._f_lat.write(header + latents)
        if self.config.fsync_every_frame:
            _fdatasync(self._f_lat)

        # Cold stream: buffered until a trigger, then written through.
        if residual is not None:
            self._residuals.push(frame_id, residual)

        # Event log (Pattern 2: no residual pointers — disk is truth).
        entry: Dict[str, Any] = {
            "frame_id": frame_id,
            "robot_id": self.robot_id,
            "selected_action": selected_action,
            "action_distribution": action_distribution,
            "stream_refs": {
                "latents": {
                    "file": "cam_latents.bin",
                    "offset": lat_offset,
                    "length": LATENT_REC_LEN,
                }
            },
        }
        if event:
            entry.update(event)
        self._f_log.write(json.dumps(entry).encode("utf-8") + b"\n")

        return FrameRef(frame_id=frame_id, offset=lat_offset)

    def trigger(self) -> None:
        """Flash Freeze: flush the residual pre-window, arm the post-window."""
        self._triggered = True
        self._residuals.trigger()

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def frames_recorded(self) -> int:
        return self._next_frame_id

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> Path:
        if self._closed:
            return self.path
        self._closed = True
        for f in (self._f_lat, self._f_res, self._f_log):
            f.close()
        (self.path / "meta.json").write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "robot_id": self.robot_id,
                    "started_at": self._started_at.isoformat().replace("+00:00", "Z"),
                    "frames": self._next_frame_id,
                    "triggered": self._triggered,
                },
                indent=2,
            )
        )
        return self.path

    def __enter__(self) -> "CapsuleRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
