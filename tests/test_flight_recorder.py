"""Flight recorder + compiler: the Phase 2 guarantees, on the v1 kernel.

Safe run -> 0-byte cold stream. Crash run -> pre/post window flushed.
Compiled capsule -> genesis-verifiable shard with embodied@1 checked.
Corrupted binary -> StrictJudge kills the compile (disk is truth).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axm_verify.logic import verify_shard

from axm_embodied.compile import compile_capsule
from axm_embodied.recorder import RecorderConfig, CapsuleRecorder
from axm_embodied_core.protocol import FILE_HEADER_LEN, LATENT_REC_LEN

from conftest import FRAMES, record_mission


def _write_pub(tmp_path: Path, pub: bytes) -> Path:
    p = tmp_path / "trusted.pub"
    p.write_bytes(pub)
    return p


def test_safe_run_keeps_cold_stream_empty(tmp_path):
    cap = record_mission(tmp_path)
    assert (cap / "cam_residuals.bin").stat().st_size == 0
    # Hot stream: file magic + exactly one record per frame.
    expected = FILE_HEADER_LEN + FRAMES * LATENT_REC_LEN
    assert (cap / "cam_latents.bin").stat().st_size == expected
    meta = json.loads((cap / "meta.json").read_text())
    assert meta["frames"] == FRAMES
    assert meta["triggered"] is False


def test_crash_run_flushes_pre_and_post_window(tmp_path):
    cfg = RecorderConfig()
    cap = record_mission(tmp_path, fault_at=25)
    size = (cap / "cam_residuals.bin").stat().st_size
    assert size > 0
    # pre-window + post-window records, 13-byte header + payload each
    expected_records = cfg.pre_window_frames + cfg.post_window_frames
    assert size == expected_records * (13 + 1024)


def test_recorder_rejects_short_latents(tmp_path):
    rec = CapsuleRecorder(tmp_path, robot_id="t")
    with pytest.raises(ValueError, match="exactly"):
        rec.record_frame(b"short", "maintain_speed", {"maintain_speed": 1.0})
    rec.close()


def test_crash_capsule_compiles_to_verified_shard(tmp_path, robot_keys):
    pub, key = robot_keys
    cap = record_mission(tmp_path, fault_at=25)
    out = tmp_path / "shard"
    shard_id = compile_capsule(cap, out, key)
    assert shard_id.startswith("sh1_")

    # Streams sealed in content/, indexed in ext/streams@1.jsonl
    assert (out / "content" / "cam_latents.bin").exists()
    assert (out / "content" / "cam_residuals.bin").exists()
    assert (out / "ext" / "streams@1.jsonl").stat().st_size > 0

    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest["profiles"] == ["embodied@1"]
    assert {s["path"] for s in manifest["sources"]} == {
        "content/source.txt",
        "content/cam_latents.bin",
        "content/cam_residuals.bin",
    }

    result = verify_shard(out, trusted_key_path=_write_pub(tmp_path, pub))
    assert result["status"] == "PASS", result["errors"]
    assert "embodied@1" in result["profiles_checked"]


def test_corrupted_latents_kill_the_compile(tmp_path, robot_keys):
    cap = record_mission(tmp_path, fault_at=25)
    lat = cap / "cam_latents.bin"
    b = bytearray(lat.read_bytes())
    b[FILE_HEADER_LEN + 8] ^= 0x01  # flip a frame_id byte -> offset drift
    lat.write_bytes(bytes(b))

    with pytest.raises(ValueError, match="DRIFT|BAD_MAGIC|OFFSET"):
        compile_capsule(cap, tmp_path / "shard_fail", robot_keys[1])


def test_frame_gap_fails_profile_verification(tmp_path, robot_keys):
    """Cutting a frame out of the hot stream is spoliation: the events log
    still verifies line-by-line up to the cut... but the sealed shard can
    never pass the embodied@1 continuity check."""
    pub, key = robot_keys
    cap = record_mission(tmp_path, fault_at=25)
    out = tmp_path / "shard"
    compile_capsule(cap, out, key)

    # Excise frame 10's record from the SEALED shard's hot stream.
    sealed = out / "content" / "cam_latents.bin"
    raw = bytearray(sealed.read_bytes())
    start = FILE_HEADER_LEN + 10 * LATENT_REC_LEN
    del raw[start:start + LATENT_REC_LEN]
    sealed.write_bytes(bytes(raw))

    result = verify_shard(out, trusted_key_path=_write_pub(tmp_path, pub))
    assert result["status"] == "FAIL"
    codes = {e["code"] for e in result["errors"]}
    # Tampering trips the Merkle/hash layer; a gap-only forgery (re-hashed
    # by an attacker without the key) would trip E_BUFFER_DISCONTINUITY.
    assert codes & {"E_MERKLE_MISMATCH", "E_MANIFEST_SCHEMA", "E_BUFFER_DISCONTINUITY"}
