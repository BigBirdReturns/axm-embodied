"""Frame Capture v0: event-triggered opaque frames, chained, judged, sealed.

Safe (untriggered) session -> nothing kept, nothing to seal. Triggered session
-> pre/post window kept with a verifiable continuity chain. Tampered bytes,
broken chains, or a lying log kill the compile (disk is truth). The compiled
capsule is a genesis-verifiable shard whose frames ride verbatim.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from axm_verify.logic import verify_shard

from axm_embodied.frame_capture import (
    FILE_HEADER_LEN,
    FRAME_REC_FIXED_LEN,
    MAGIC_FRAME_FILE,
    PHYSICAL_TIER,
    FrameCaptureConfig,
    FrameCaptureRecorder,
    FrameJudge,
    chain_genesis,
    chain_next,
)
from axm_embodied.frame_compile import compile_frame_capsule

FRAME_BYTES = 512
CFG = FrameCaptureConfig(pre_window_frames=5, post_window_frames=5)


def _frame(i: int) -> bytes:
    """Deterministic opaque sensor payload (the recorder never parses it)."""
    return hashlib.sha256(f"frame-{i}".encode()).digest() * (FRAME_BYTES // 32)


def _session(out_dir: Path, *, frames: int = 30, trigger_at: int | None = 15,
             triggers: tuple[int, ...] | None = None) -> Path:
    fire_at = set(triggers if triggers is not None else ([] if trigger_at is None else [trigger_at]))
    with FrameCaptureRecorder(out_dir, sensor_id="doorcam-01",
                              session_id="test-session", config=CFG) as rec:
        for i in range(frames):
            if i in fire_at:
                rec.trigger(reason="motion", source="pir-sensor-3")
            rec.observe_frame(_frame(i))
    return rec.path


def _write_pub(tmp_path: Path, pub: bytes) -> Path:
    p = tmp_path / "trusted.pub"
    p.write_bytes(pub)
    return p


# ── recorder: event-triggered honesty ────────────────────────────────────


def test_untriggered_session_keeps_nothing(tmp_path):
    cap = _session(tmp_path, trigger_at=None)
    assert (cap / "frames.bin").stat().st_size == FILE_HEADER_LEN  # magic only
    manifest = json.loads((cap / "capture_manifest.json").read_text())
    assert manifest["frames_observed"] == 30 and manifest["frames_kept"] == 0
    assert manifest["evidence_tier"] == PHYSICAL_TIER == "physical_capture"
    assert "not identity" in manifest["evidence_tier_limits"]


def test_trigger_keeps_pre_and_post_window_with_monotonic_visible_ids(tmp_path):
    cap = _session(tmp_path, trigger_at=15)
    rows = FrameJudge(cap).verify()
    # pre-window = frames 10..14, post-window = frames 15..19
    assert [r["frame_id"] for r in rows] == list(range(10, 20))
    size = (cap / "frames.bin").stat().st_size
    assert size == FILE_HEADER_LEN + 10 * (FRAME_REC_FIXED_LEN + FRAME_BYTES)


def test_two_windows_declare_the_gap_and_chain_spans_it(tmp_path):
    cap = _session(tmp_path, frames=40, triggers=(10, 30))
    rows = FrameJudge(cap).verify()
    kept = [r["frame_id"] for r in rows]
    assert kept == list(range(5, 15)) + list(range(25, 35))  # gap 15..24 visible
    # the chain runs unbroken ACROSS the declared gap
    chain = chain_genesis("test-session")
    for r in rows:
        chain = chain_next(chain, bytes.fromhex(r["content_sha256"]), r["frame_id"])
        assert chain.hex() == r["chain"]
    events = [json.loads(l) for l in (cap / "events.jsonl").read_text().splitlines()]
    assert sum(e["evt"] == "capture_window_opened" for e in events) == 2
    assert sum(e["evt"] == "capture_window_closed" for e in events) == 2


def test_trigger_requires_declared_reason_and_source(tmp_path):
    rec = FrameCaptureRecorder(tmp_path, sensor_id="cam")
    with pytest.raises(ValueError, match="never inferred"):
        rec.trigger(reason="", source="pir")
    with pytest.raises(ValueError, match="never inferred"):
        rec.trigger(reason="motion", source="  ")
    rec.close()


def test_oversized_and_empty_frames_are_rejected(tmp_path):
    rec = FrameCaptureRecorder(tmp_path, sensor_id="cam",
                               config=FrameCaptureConfig(max_frame_bytes=64))
    with pytest.raises(ValueError, match="exceeds"):
        rec.observe_frame(b"x" * 65)
    with pytest.raises(ValueError, match="non-empty"):
        rec.observe_frame(b"")
    rec.close()


def test_frames_are_opaque_bytes_never_parsed(tmp_path):
    # Arbitrary non-image bytes record fine: the recorder does not decode.
    with FrameCaptureRecorder(tmp_path, sensor_id="cam", config=CFG) as rec:
        rec.trigger(reason="test", source="unit")
        ref = rec.observe_frame(b"\x00\xff definitely not a real image \x7f")
    assert ref is not None
    assert ref.content_sha256 == hashlib.sha256(b"\x00\xff definitely not a real image \x7f").hexdigest()


# ── judge: disk is truth ─────────────────────────────────────────────────


def test_judge_verifies_clean_capsule(tmp_path):
    cap = _session(tmp_path)
    rows = FrameJudge(cap).verify()
    assert len(rows) == 10
    assert all(r["content_sha256"] and r["chain"] for r in rows)


def test_tampered_payload_byte_breaks_the_hash(tmp_path):
    cap = _session(tmp_path)
    fb = cap / "frames.bin"
    b = bytearray(fb.read_bytes())
    b[-1] ^= 0x01  # flip one payload byte in the last frame
    fb.write_bytes(bytes(b))
    with pytest.raises(ValueError, match="payload hash mismatch"):
        FrameJudge(cap).verify()


def test_removed_record_breaks_the_continuity_chain(tmp_path):
    cap = _session(tmp_path)
    fb = cap / "frames.bin"
    raw = fb.read_bytes()
    rec_len = FRAME_REC_FIXED_LEN + FRAME_BYTES
    # excise the FIRST kept record: later records' chains no longer verify
    fb.write_bytes(raw[:FILE_HEADER_LEN] + raw[FILE_HEADER_LEN + rec_len:])
    with pytest.raises(ValueError, match="chain broken"):
        FrameJudge(cap).verify()


def test_lying_log_is_fatal(tmp_path):
    cap = _session(tmp_path)
    ev = cap / "events.jsonl"
    lines = ev.read_text().splitlines()
    doctored = []
    for line in lines:
        evt = json.loads(line)
        if evt.get("evt") == "frame_kept" and evt["frame_id"] == 12:
            evt["content_sha256"] = "00" * 32  # log now disagrees with disk
        doctored.append(json.dumps(evt))
    ev.write_text("\n".join(doctored) + "\n")
    with pytest.raises(ValueError, match="disagrees with disk"):
        FrameJudge(cap).verify()


# ── compile: sealed through the genesis kernel ───────────────────────────


def test_capsule_compiles_to_verified_shard(tmp_path, robot_keys):
    pub, key = robot_keys
    cap = _session(tmp_path)
    out = tmp_path / "shard"
    shard_id = compile_frame_capsule(cap, out, key, timestamp="2026-07-06T00:00:00Z")
    assert shard_id.startswith("sh1_")

    # frames sealed verbatim in content/, indexed in ext/frames@1.jsonl
    assert (out / "content" / "frames.bin").read_bytes() == (cap / "frames.bin").read_bytes()
    sealed_manifest = json.loads((out / "content" / "capture_manifest.json").read_text())
    assert sealed_manifest["evidence_tier"] == "physical_capture"
    rows = [json.loads(l) for l in (out / "ext" / "streams@1.jsonl").read_text().splitlines()]
    assert len(rows) == 10
    assert all(r["stream"] == "frames" and r["file"] == "frames.bin" and r["content_hash"] for r in rows)
    # the continuity chain is sealed inside the source: every frame_kept line
    # (verbatim in content/source.txt) carries its chain hash
    sealed_source = (out / "content" / "source.txt").read_text()
    judge_records = FrameJudge(cap).verify()
    for rec in judge_records:
        assert rec["chain"] in sealed_source

    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest.get("profiles", []) == []  # deliberately NOT embodied@1 (no VLA hot stream)

    result = verify_shard(out, trusted_key_path=_write_pub(tmp_path, pub))
    assert result["status"] == "PASS", result.get("errors")


def test_wrong_key_fails_verification(tmp_path, robot_keys, school_keys):
    _pub, key = robot_keys
    wrong_pub, _ = school_keys
    cap = _session(tmp_path)
    out = tmp_path / "shard"
    compile_frame_capsule(cap, out, key, timestamp="2026-07-06T00:00:00Z")
    result = verify_shard(out, trusted_key_path=_write_pub(tmp_path, wrong_pub))
    assert result["status"] != "PASS"


def test_tampered_capsule_never_compiles(tmp_path, robot_keys):
    cap = _session(tmp_path)
    fb = cap / "frames.bin"
    b = bytearray(fb.read_bytes())
    b[-1] ^= 0x01
    fb.write_bytes(bytes(b))
    with pytest.raises(ValueError, match="payload hash mismatch"):
        compile_frame_capsule(cap, tmp_path / "shard_fail", robot_keys[1])


def test_untriggered_capsule_refuses_to_compile(tmp_path, robot_keys):
    cap = _session(tmp_path, trigger_at=None)
    with pytest.raises(ValueError, match="No candidates"):
        compile_frame_capsule(cap, tmp_path / "shard_none", robot_keys[1])


def test_wrong_tier_capsule_is_refused(tmp_path, robot_keys):
    cap = _session(tmp_path)
    mp = cap / "capture_manifest.json"
    doc = json.loads(mp.read_text())
    doc["evidence_tier"] = "platform_record"
    mp.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="physical captures only"):
        compile_frame_capsule(cap, tmp_path / "shard_tier", robot_keys[1])


def test_detached_verification_via_cli(tmp_path, robot_keys):
    # Only the shard bytes + the out-of-band pub: no recorder, no camera, no
    # spoke code in the loop.
    pub, key = robot_keys
    cap = _session(tmp_path)
    out = tmp_path / "shard"
    compile_frame_capsule(cap, out, key, timestamp="2026-07-06T00:00:00Z")
    proc = subprocess.run(
        ["axm-verify", "shard", str(out), "--trusted-key", str(_write_pub(tmp_path, pub))],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── boundaries: no filtering, no vision, no cross-spoke import ───────────


def test_no_vision_ocr_or_cross_spoke_imports():
    code = (
        "import importlib, sys\n"
        "sys.path.insert(0, 'src')\n"
        "importlib.import_module('axm_embodied.frame_capture')\n"
        "importlib.import_module('axm_embodied.frame_compile')\n"
        "bad=[m for m in ('PIL','cv2','torch','pytesseract','easyocr','transformers',"
        "'numpy','ghostbox','screenghost') "
        "if any(k==m or k.startswith(m+'.') for k in sys.modules)]\n"
        "print('BAD:'+','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parent.parent))
    assert out.returncode == 0, out.stderr
    assert [l for l in out.stdout.splitlines() if l.startswith("BAD:")][0] == "BAD:"
