"""Embodied Frame Capture v0 — event-triggered camera frames as sealed evidence.

The camera-frame sibling of the Flash Freeze recorder. Where the flight
recorder captures what a VLA perceived and chose (latents + residuals), this
captures what a *sensor* saw (full frames) around a declared trigger — a home
camera, a doorbell, a hazard cam — with the same discipline:

- **Frames are opaque sensor bytes.** The recorder never decodes, transcodes,
  filters, classifies, or interprets them. No vision model, no OCR. What the
  sensor emitted is what gets hashed and sealed, byte for byte.
- **Event-triggered, honestly.** Frames are observed continuously but KEPT only
  in a pre/post window around an explicit trigger (mirroring the cold-stream
  ``ResidualBuffer``). The trigger's reason and source are CALLER-SUPPLIED —
  a motion sensor id, a doorbell press — never inferred from the pixels.
- **Continuity is a hash chain.** Every kept record carries the SHA-256 of its
  payload and a chain hash over (previous chain ‖ payload hash ‖ frame id).
  Frame ids stay globally monotonic across the whole session, so the gaps
  between capture windows are *visible and declared* (window events in the
  log), never silently spliced. A break in the chain is itself a finding.
- **Disk is truth.** ``FrameJudge`` rescans ``frames.bin`` and recomputes every
  hash and the full chain before anything is sealed; a capsule whose log
  disagrees with its bytes never compiles.

Evidence tier is explicit and bounded — ``physical_capture``: sensor bytes
within declared trigger windows. NOT identity, NOT activity or semantic
classification, NOT continuous coverage, NOT platform truth, NOT legal-grade
provenance by itself.

On-disk magics are local to this stream (``AXFF``/``AXFR``) and use the same
13-byte record-header layout as the core protocol; they are kept here rather
than in ``axm_embodied_core.protocol`` so the frozen recorder/judge pair is
untouched — promotion into the core protocol file is a review decision.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from axm_embodied_core.protocol import REC_HEADER_FMT, REC_HEADER_LEN, VERSION

# Frame-stream magics (see module docstring for placement rationale).
MAGIC_FRAME_FILE = b"AXFF"  # frames.bin file header
MAGIC_FRAME_REC = b"AXFR"   # one kept-frame record

FILE_HEADER_LEN = 4
HASH_LEN = 32               # sha256 digest size
# Record: [Magic(4)|Ver(1)|FrameID(4)|Length(4)] | payload_sha256(32) | chain(32) | payload
FRAME_REC_FIXED_LEN = REC_HEADER_LEN + HASH_LEN + HASH_LEN

DEFAULT_MAX_FRAME_BYTES = 32 * 1024 * 1024  # 32 MiB per frame, zip-bomb guard

PHYSICAL_TIER = "physical_capture"
PHYSICAL_TIER_LIMITS = (
    "opaque sensor bytes within declared trigger windows only",
    "not identity",
    "not activity or semantic classification",
    "not continuous coverage (gaps between windows are declared, not hidden)",
    "not platform truth",
    "not legal-grade provenance by itself",
)


def _fdatasync(fileobj) -> None:
    fileobj.flush()
    if hasattr(os, "fdatasync"):
        os.fdatasync(fileobj.fileno())
    else:  # pragma: no cover — non-POSIX fallback
        os.fsync(fileobj.fileno())


def chain_genesis(session_id: str) -> bytes:
    """First link of the continuity chain, bound to the session identity."""
    return hashlib.sha256(b"axm-embodied/frames@1:" + session_id.encode("utf-8")).digest()


def chain_next(prev_chain: bytes, payload_sha256: bytes, frame_id: int) -> bytes:
    """chain_n = SHA256(chain_{n-1} ‖ payload_hash ‖ frame_id_le32)."""
    return hashlib.sha256(prev_chain + payload_sha256 + struct.pack("<I", frame_id)).digest()


@dataclass(frozen=True)
class FrameCaptureConfig:
    """Ring-buffer windows in frames; per-frame size guard."""

    pre_window_frames: int = 10   # history kept when a trigger fires
    post_window_frames: int = 10  # frames kept after a trigger
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES


@dataclass(frozen=True)
class KeptFrameRef:
    """Where a kept frame's record landed, plus its evidence hashes."""

    frame_id: int
    offset: int
    length: int             # full record length (header + hashes + payload)
    content_sha256: str
    chain: str


class FrameCaptureRecorder:
    """Record one camera-capture session: frames.bin + events.jsonl + meta.

    Usage::

        with FrameCaptureRecorder(out, sensor_id="doorcam-01") as rec:
            for frame in camera:
                rec.observe_frame(frame)
                if motion_sensor.fired:
                    rec.trigger(reason="motion", source="pir-sensor-3")
        capsule = rec.path
    """

    def __init__(
        self,
        out_dir: Path | str,
        sensor_id: str,
        session_id: Optional[str] = None,
        config: FrameCaptureConfig = FrameCaptureConfig(),
    ) -> None:
        self.sensor_id = sensor_id
        self.session_id = session_id or str(uuid.uuid4())
        self.config = config
        self.path = Path(out_dir) / f"capture-{self.session_id[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)

        self._f_frames = open(self.path / "frames.bin", "wb")
        self._f_log = open(self.path / "events.jsonl", "wb")
        self._f_frames.write(MAGIC_FRAME_FILE)

        # Pre-window ring buffer of (frame_id, payload). Chain hashes are
        # computed at WRITE time so the chain covers kept records in disk order.
        self._buffer: deque[tuple[int, bytes]] = deque(maxlen=config.pre_window_frames)
        self._post_left = 0
        self._chain = chain_genesis(self.session_id)
        self._next_frame_id = 0
        self._frames_kept = 0
        self._triggers = 0
        self._window_open = False
        self._closed = False
        self._started_at = datetime.now(timezone.utc)

    # ── Recording ────────────────────────────────────────────────────────

    def observe_frame(self, frame: bytes) -> Optional[KeptFrameRef]:
        """Observe one sensor frame (opaque bytes).

        Every observed frame consumes a monotonic frame id — kept or not — so
        the ids inside sealed windows expose exactly how much was NOT kept.
        Returns a :class:`KeptFrameRef` when the frame was written to disk
        (inside a triggered window), else ``None`` (buffered / discarded).
        """
        if self._closed:
            raise RuntimeError("FrameCaptureRecorder is closed")
        if not isinstance(frame, (bytes, bytearray)) or len(frame) == 0:
            raise ValueError("frame must be non-empty bytes (opaque sensor payload)")
        if len(frame) > self.config.max_frame_bytes:
            raise ValueError(
                f"frame of {len(frame)} bytes exceeds max_frame_bytes="
                f"{self.config.max_frame_bytes}"
            )

        frame_id = self._next_frame_id
        self._next_frame_id += 1

        if self._post_left > 0:
            ref = self._write_record(frame_id, bytes(frame))
            self._post_left -= 1
            if self._post_left == 0:
                _fdatasync(self._f_frames)
                self._log({"evt": "capture_window_closed", "frame_id": frame_id,
                           "sensor_id": self.sensor_id})
                self._window_open = False
            return ref

        self._buffer.append((frame_id, bytes(frame)))
        return None

    def trigger(self, *, reason: str, source: str) -> None:
        """Declare a capture trigger. ``reason`` and ``source`` are supplied by
        the caller (a motion sensor id, a doorbell, an operator) — this module
        never infers a trigger from the pixels."""
        if self._closed:
            raise RuntimeError("FrameCaptureRecorder is closed")
        if not (reason and reason.strip()) or not (source and source.strip()):
            raise ValueError(
                "a trigger must declare an explicit reason and source; "
                "triggers are never inferred from frame content"
            )
        self._triggers += 1
        trigger_frame = self._next_frame_id  # the id the NEXT observed frame gets
        self._log({"evt": "capture_trigger", "frame_id": trigger_frame,
                   "reason": reason, "source": source, "sensor_id": self.sensor_id})
        if self._post_left > 0:
            # Already inside a window: extend the post-window, one declaration.
            self._post_left = self.config.post_window_frames
            return
        first_kept = self._buffer[0][0] if self._buffer else trigger_frame
        self._log({"evt": "capture_window_opened", "frame_id": trigger_frame,
                   "first_kept_frame_id": first_kept, "sensor_id": self.sensor_id})
        self._window_open = True
        while self._buffer:
            fid, payload = self._buffer.popleft()
            self._write_record(fid, payload)
        _fdatasync(self._f_frames)  # durability: commit the history
        self._post_left = self.config.post_window_frames

    def _write_record(self, frame_id: int, payload: bytes) -> KeptFrameRef:
        payload_hash = hashlib.sha256(payload).digest()
        self._chain = chain_next(self._chain, payload_hash, frame_id)
        offset = self._f_frames.tell()
        header = struct.pack(REC_HEADER_FMT, MAGIC_FRAME_REC, VERSION, frame_id, len(payload))
        self._f_frames.write(header + payload_hash + self._chain + payload)
        length = FRAME_REC_FIXED_LEN + len(payload)
        ref = KeptFrameRef(
            frame_id=frame_id,
            offset=offset,
            length=length,
            content_sha256=payload_hash.hex(),
            chain=self._chain.hex(),
        )
        self._frames_kept += 1
        self._log({
            "evt": "frame_kept",
            "frame_id": frame_id,
            "sensor_id": self.sensor_id,
            "stream_refs": {"frames": {"file": "frames.bin", "offset": offset, "length": length}},
            "content_sha256": ref.content_sha256,
            "chain": ref.chain,
        })
        return ref

    def _log(self, entry: Dict[str, Any]) -> None:
        self._f_log.write(json.dumps(entry).encode("utf-8") + b"\n")

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def frames_observed(self) -> int:
        return self._next_frame_id

    @property
    def frames_kept(self) -> int:
        return self._frames_kept

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> Path:
        if self._closed:
            return self.path
        self._closed = True
        if self._window_open:
            self._log({"evt": "capture_window_closed", "frame_id": self._next_frame_id - 1,
                       "sensor_id": self.sensor_id, "note": "session ended inside window"})
        for f in (self._f_frames, self._f_log):
            f.close()
        (self.path / "capture_manifest.json").write_text(
            json.dumps(
                {
                    "evidence_tier": PHYSICAL_TIER,
                    "evidence_tier_limits": list(PHYSICAL_TIER_LIMITS),
                    "session_id": self.session_id,
                    "sensor_id": self.sensor_id,
                    "started_at": self._started_at.isoformat().replace("+00:00", "Z"),
                    "frames_observed": self._next_frame_id,
                    "frames_kept": self._frames_kept,
                    "triggers": self._triggers,
                    "chain_genesis": chain_genesis(self.session_id).hex(),
                    "note": "frames are opaque sensor bytes; never decoded, filtered, "
                            "classified, or interpreted by this recorder",
                },
                indent=2,
            )
        )
        return self.path

    def __enter__(self) -> "FrameCaptureRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ─────────────────────────────────────────────────────────────────────────
# FrameJudge — disk is truth
# ─────────────────────────────────────────────────────────────────────────


class FrameJudge:
    """Rescan frames.bin, recompute every hash and the full continuity chain,
    and cross-check the event log's claims. Any disagreement is FATAL: a
    capsule whose log disagrees with its bytes never compiles."""

    def __init__(self, capsule_path: Path | str, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES):
        self.capsule_path = Path(capsule_path)
        self.max_frame_bytes = max_frame_bytes

    def verify(self) -> List[Dict[str, Any]]:
        """Verify the whole capsule and return one record per kept frame
        (offset, length, content hash, chain). Raises ValueError on any hash
        break, chain break, torn record, or log/disk disagreement.

        The sealed ``ext/streams@1.jsonl`` index derives from these records via
        :func:`streams_rows` — the kernel's registered stream-index schema has
        no chain column, and needs none: the chain is already sealed twice
        (embedded in every ``frames.bin`` record inside the Merkle tree, and
        verbatim in the ``frame_kept`` lines of the sealed source)."""
        manifest = json.loads((self.capsule_path / "capture_manifest.json").read_text())
        session_id = manifest["session_id"]

        records = self._scan_frames(session_id)
        self._cross_check_log(records)
        return records

    def _scan_frames(self, session_id: str) -> List[Dict[str, Any]]:
        path = self.capsule_path / "frames.bin"
        records: List[Dict[str, Any]] = []
        chain = chain_genesis(session_id)
        last_fid = -1
        with open(path, "rb") as f:
            if f.read(FILE_HEADER_LEN) != MAGIC_FRAME_FILE:
                raise ValueError("FATAL: invalid frames.bin file header")
            while True:
                offset = f.tell()
                header = f.read(REC_HEADER_LEN)
                if len(header) == 0:
                    break  # clean EOF
                if len(header) < REC_HEADER_LEN:
                    raise ValueError(f"FATAL: torn frame header at offset {offset}")
                magic, ver, fid, dlen = struct.unpack(REC_HEADER_FMT, header)
                if magic != MAGIC_FRAME_REC:
                    raise ValueError(f"FATAL: bad frame magic at offset {offset}")
                if ver != VERSION:
                    raise ValueError(f"FATAL: frame record version {int(ver)} at frame {int(fid)}")
                if dlen > self.max_frame_bytes:
                    raise ValueError(f"FATAL: frame payload {int(dlen)} exceeds limit")
                if int(fid) <= last_fid:
                    raise ValueError(
                        f"FATAL: frame ids not strictly increasing at offset {offset} "
                        f"({int(fid)} after {last_fid})"
                    )
                claimed_payload_hash = f.read(HASH_LEN)
                claimed_chain = f.read(HASH_LEN)
                payload = f.read(dlen)
                if len(claimed_payload_hash) < HASH_LEN or len(claimed_chain) < HASH_LEN or len(payload) != dlen:
                    raise ValueError(f"FATAL: torn frame record at offset {offset}")

                actual_hash = hashlib.sha256(payload).digest()
                if actual_hash != claimed_payload_hash:
                    raise ValueError(
                        f"FATAL: frame {int(fid)} payload hash mismatch — bytes on disk "
                        f"do not match the recorded evidence hash"
                    )
                chain = chain_next(chain, actual_hash, int(fid))
                if chain != claimed_chain:
                    raise ValueError(
                        f"FATAL: continuity chain broken at frame {int(fid)} — a record "
                        f"was altered, removed, or reordered"
                    )
                last_fid = int(fid)
                records.append(
                    {
                        "frame_id": int(fid),
                        "offset": offset,
                        "length": FRAME_REC_FIXED_LEN + dlen,
                        "content_sha256": actual_hash.hex(),
                        "chain": chain.hex(),
                    }
                )
        return records

    @staticmethod
    def streams_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Judge records -> kernel ``streams@1`` rows (registered schema)."""
        return [
            {
                "frame_id": r["frame_id"],
                "stream": "frames",
                "file": "frames.bin",
                "offset": r["offset"],
                "length": r["length"],
                "status": "VERIFIED",
                "content_hash": r["content_sha256"],
            }
            for r in records
        ]

    def _cross_check_log(self, records: List[Dict[str, Any]]) -> None:
        """The log's frame_kept claims must agree with disk exactly."""
        by_fid = {r["frame_id"]: r for r in records}
        claimed_fids = set()
        with open(self.capsule_path / "events.jsonl", "rb") as f:
            for line in f:
                if not line.strip():
                    continue
                evt = json.loads(line)
                if evt.get("evt") != "frame_kept":
                    continue
                fid = int(evt["frame_id"])
                claimed_fids.add(fid)
                rec = by_fid.get(fid)
                if rec is None:
                    raise ValueError(f"FATAL: log claims kept frame {fid} not present on disk")
                ref = evt["stream_refs"]["frames"]
                if int(ref["offset"]) != rec["offset"] or int(ref["length"]) != rec["length"]:
                    raise ValueError(f"FATAL: log stream ref for frame {fid} disagrees with disk")
                if evt.get("content_sha256") != rec["content_sha256"]:
                    raise ValueError(f"FATAL: log content hash for frame {fid} disagrees with disk")
                if evt.get("chain") != rec["chain"]:
                    raise ValueError(f"FATAL: log chain for frame {fid} disagrees with disk")
        missing = set(by_fid) - claimed_fids
        if missing:
            raise ValueError(f"FATAL: disk has kept frames the log never claimed: {sorted(missing)}")
