#!/usr/bin/env bash
set -euo pipefail

# Board Demo: Phase 2 Pattern 2
# Usage:
#   ./scripts/board_demo.sh
#
# Requires:
#   python (with deps installed) OR uv/pipenv/poetry env
#   axm-compile and axm-verify available (via `pip install -e .`)

rm -rf demo_safe demo_crash shard_out shard_out_fail || true

echo "== Step 1: Safe baseline (0 byte residuals) =="
python tools/sim_robot.py --phase2 demo_safe --runs 1
ls -lh demo_safe/capsule-*/cam_*.bin

echo
echo "== Step 2: Crash event and shard compile =="
python tools/sim_robot.py --phase2 demo_crash --runs 1 --crash
axm-compile demo_crash/capsule-* shard_out

echo
echo "== Step 3: Verify shard integrity =="
axm-verify shard shard_out

echo
echo "== Step 4: Floating point attack (corrupt 1 byte) =="
python scripts/corrupt_one_byte.py demo_crash/capsule-*/cam_latents.bin
set +e
axm-compile demo_crash/capsule-* shard_out_fail
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "ERROR: Expected compile to fail after corruption."
  exit 1
fi
echo "PASS: Compiler rejected corrupted latents."
