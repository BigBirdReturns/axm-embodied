import shutil
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
    r = run(f"python tools/sim_robot.py --phase2 {safe_dir} --runs 1", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    cap = next(safe_dir.glob("capsule-*"))
    resid = cap / "cam_residuals.bin"
    assert resid.exists()
    assert resid.stat().st_size == 0

    # Crash run
    r = run(f"python tools/sim_robot.py --phase2 {crash_dir} --runs 1 --crash", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    cap = next(crash_dir.glob("capsule-*"))
    r = run(f"python -m axm_compile.cli {cap} {shard_out}", cwd=repo)
    assert r.returncode == 0, r.stderr + r.stdout

    streams = shard_out / "evidence" / "streams.parquet"
    assert streams.exists()
    assert streams.stat().st_size > 0

    # Corrupt and ensure failure
    lat = cap / "cam_latents.bin"
    b = bytearray(lat.read_bytes())
    b[4 + 8] ^= 0x01
    lat.write_bytes(bytes(b))

    shard_out_fail = tmp_path / "shard_out_fail"
    r = run(f"python -m axm_compile.cli {cap} {shard_out_fail}", cwd=repo)
    assert r.returncode != 0
