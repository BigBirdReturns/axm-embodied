from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import BinaryIO
from warnings import warn

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from axm_core.protocol import (
    MAGIC_LATENT_FILE,
    MAGIC_LATENT_REC,
    MAGIC_RESID_REC,
    VERSION,
    REC_HEADER_FMT,
    REC_HEADER_LEN,
    DEFAULT_MAX_RESIDUAL_SIZE,
    DEFAULT_MAX_RESYNC_BYTES,
    DEFAULT_MAX_GARBAGE_BYTES,
    FILE_HEADER_LEN,
    LATENT_REC_LEN,
    LATENT_DIM,
)


class StrictJudge:
    """Pattern 2 Judge: disk is truth.

    - Residuals are discovered by scanning cam_residuals.bin.
    - Latents are verified by strict offset math and header checks.
    """

    def __init__(self, capsule_path: Path):
        self.capsule_path = Path(capsule_path)
        self.residual_index: dict[int, dict] = {}
        self.scan_stats = {
            "corrupt_headers": 0,
            "garbage_bytes": 0,
            "resyncs": 0,
            "records": 0,
        }

        self._scan_residuals()
        self._open_latents()

    def _resync_to_magic(self, f: BinaryIO, magic_bytes: bytes, start_pos: int) -> int:
        """Scan forward to find the next magic sequence.

        Returns the absolute file offset where magic starts, or -1 if not found within budget.
        """
        chunk_size = 64 * 1024  # 64KB
        scanned = 0

        # We keep a small overlap so magic split across chunks can still be found.
        overlap = len(magic_bytes) - 1
        prev_tail = b""

        f.seek(start_pos)
        while scanned < DEFAULT_MAX_RESYNC_BYTES:
            chunk = f.read(chunk_size)
            if not chunk:
                return -1

            hay = prev_tail + chunk
            pos = hay.find(magic_bytes)
            if pos != -1:
                # f.tell() is at end of chunk; compute absolute offset of match.
                end_off = f.tell()
                start_of_hay = end_off - len(hay)
                return start_of_hay + pos

            # Prepare overlap for next iteration.
            prev_tail = hay[-overlap:] if overlap > 0 else b""
            scanned += len(chunk)

        return -1

    def _scan_residuals(self) -> None:
        res_path = self.capsule_path / "cam_residuals.bin"
        if not res_path.exists():
            return

        with open(res_path, "rb") as f:
            while True:
                start_off = f.tell()
                header = f.read(REC_HEADER_LEN)

                # Clean EOF
                if len(header) == 0:
                    break

                # Truncated header
                if len(header) < REC_HEADER_LEN:
                    warn(f"Truncated residual header at offset {start_off}")
                    break

                magic, ver, fid, dlen = struct.unpack(REC_HEADER_FMT, header)

                # 1. Magic check and resync
                if magic != MAGIC_RESID_REC:
                    self.scan_stats["corrupt_headers"] += 1
                    warn(f"Corrupt residual magic {magic!r} at offset {start_off}. Resyncing.")

                    next_off = self._resync_to_magic(f, MAGIC_RESID_REC, start_off + 1)
                    if next_off == -1:
                        warn("Unable to resync residual stream. Stopping scan.")
                        break

                    garbage = next_off - start_off
                    self.scan_stats["garbage_bytes"] += int(garbage)
                    self.scan_stats["resyncs"] += 1

                    if garbage > DEFAULT_MAX_GARBAGE_BYTES:
                        warn(f"Large garbage span during resync: {garbage} bytes")

                    f.seek(next_off)
                    continue

                # 2. Sanity checks
                if ver != VERSION:
                    raise ValueError(f"FATAL: Residual version mismatch {int(ver)} at frame {int(fid)}")

                # Zip bomb protection
                if dlen > DEFAULT_MAX_RESIDUAL_SIZE:
                    raise ValueError(
                        f"FATAL: Residual payload size {int(dlen)} exceeds limit {DEFAULT_MAX_RESIDUAL_SIZE}"
                    )

                # 3. Payload read
                data = f.read(dlen)
                if len(data) != dlen:
                    warn(f"Torn residual payload at frame {int(fid)}. Stopping scan.")
                    break

                self.residual_index[int(fid)] = {
                    "offset": int(start_off),
                    "length": int(REC_HEADER_LEN + dlen),
                    "content_hash": hashlib.sha256(data).hexdigest(),
                    "status": "VERIFIED",
                }
                self.scan_stats["records"] += 1

    def _open_latents(self) -> None:
        lat_path = self.capsule_path / "cam_latents.bin"
        self.f_lat = open(lat_path, "rb")
        file_magic = self.f_lat.read(FILE_HEADER_LEN)
        if file_magic != MAGIC_LATENT_FILE:
            raise ValueError("FATAL: Invalid latent file header")

    def get_scan_stats(self) -> dict:
        return dict(self.scan_stats)

    def verify_latent(self, claimed_offset: int, claimed_len: int, expected_fid: int) -> tuple[str, str | None]:
        # Strict offset math assertion
        math_offset = FILE_HEADER_LEN + (expected_fid * LATENT_REC_LEN)

        if claimed_offset != math_offset:
            return f"OFFSET_MISMATCH (Claimed {claimed_offset} != Math {math_offset})", None
        if claimed_len != LATENT_REC_LEN:
            return f"LEN_MISMATCH (Claimed {claimed_len} != Const {LATENT_REC_LEN})", None

        # Physical verification
        self.f_lat.seek(claimed_offset)
        header = self.f_lat.read(REC_HEADER_LEN)
        if len(header) < REC_HEADER_LEN:
            return "EOF", None

        magic, ver, fid, dlen = struct.unpack(REC_HEADER_FMT, header)

        if magic != MAGIC_LATENT_REC:
            return "BAD_MAGIC", None
        if ver != VERSION:
            return "BAD_VERSION", None
        if int(fid) != expected_fid:
            return f"DRIFT (Found {int(fid)}, Exp {expected_fid})", None
        if int(dlen) != LATENT_DIM:
            return f"BAD_DIM (Found {int(dlen)}, Exp {LATENT_DIM})", None

        data = self.f_lat.read(dlen)
        if len(data) != dlen:
            return "TORN_WRITE", None

        return "VERIFIED", hashlib.sha256(data).hexdigest()


def compile_streams_evidence(capsule_path: Path, out_path: Path) -> None:
    """Build evidence/streams.parquet for Phase 2."""
    judge = StrictJudge(capsule_path)
    evidence: list[dict] = []

    events_path = Path(capsule_path) / "events.jsonl"
    with open(events_path, "rb") as f:
        for line in f:
            evt = json.loads(line)
            fid = int(evt["frame_id"])

            l_ref = evt["stream_refs"]["latents"]
            stat, h = judge.verify_latent(int(l_ref["offset"]), int(l_ref["length"]), fid)
            if stat != "VERIFIED":
                raise ValueError(f"FATAL Frame {fid}: {stat}")

            evidence.append(
                {
                    "frame_id": fid,
                    "stream": "latents",
                    "file": "cam_latents.bin",
                    "offset": int(l_ref["offset"]),
                    "length": int(l_ref["length"]),
                    "status": stat,
                    "content_hash": h,
                }
            )

            if fid in judge.residual_index:
                rec = judge.residual_index[fid]
                evidence.append(
                    {
                        "frame_id": fid,
                        "stream": "residuals",
                        "file": "cam_residuals.bin",
                        "offset": int(rec["offset"]),
                        "length": int(rec["length"]),
                        "status": rec["status"],
                        "content_hash": rec["content_hash"],
                    }
                )

    (Path(out_path) / "evidence").mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(evidence)
    if df.empty:
        return

    schema = pa.schema(
        [
            ("frame_id", pa.int32()),
            ("stream", pa.string()),
            ("file", pa.string()),
            ("offset", pa.int64()),
            ("length", pa.int32()),
            ("status", pa.string()),
            ("content_hash", pa.string()),
        ]
    )

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    pq.write_table(table, Path(out_path) / "evidence/streams.parquet")
