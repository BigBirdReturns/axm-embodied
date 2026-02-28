import subprocess
from pathlib import Path


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, check=False, capture_output=True, text=True)


def test_safe_and_crash_pattern2(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    safe_dir = tmp_path / "demo_safe"
    crash_dir = tmp_path / "demo_crash"
    shard_out = tmp_path / "shard_out"

    # Safe run
    r = run(f"python tools/sim_robot_final.py --out {safe_dir}", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    cap = next(safe_dir.glob("capsule-*"))
    resid = cap / "cam_residuals.bin"
    assert resid.exists()
    assert resid.stat().st_size == 0

    # Crash run
    r = run(f"python tools/sim_robot_final.py --out {crash_dir} --crash", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    cap = next(crash_dir.glob("capsule-*"))

    # Compile via axm-compile CLI (src/axm_embodied/compile.py)
    r = run(f"axm-compile {cap} {shard_out} --legacy", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    streams = shard_out / "ext" / "streams@1.parquet"
    assert streams.exists(), "streams@1.parquet should be in ext/"
    assert streams.stat().st_size > 0

    # Genesis verification — proves the spoke produces verifiable shards
    from axm_verify.logic import verify_shard
    result = verify_shard(
        shard_out,
        trusted_key_path=shard_out / "sig" / "publisher.pub"
    )
    assert result["status"] == "PASS", \
        f"axm-verify failed on compiled embodied shard: {result['errors']}"

    # Corrupt and ensure StrictJudge rejects
    lat = cap / "cam_latents.bin"
    b = bytearray(lat.read_bytes())
    b[4 + 8] ^= 0x01
    lat.write_bytes(bytes(b))

    shard_out_fail = tmp_path / "shard_out_fail"
    r = run(f"axm-compile {cap} {shard_out_fail} --legacy", cwd=repo)
    assert r.returncode != 0, "Expected FATAL on corrupted latents"
