#!/usr/bin/env bash
set -e

echo "=== SAFE RUN ==="
python tools/sim_robot_final.py
echo "Residual size (safe):"
ls -lh capsules_final/*/cam_residuals.bin || true

echo ""
echo "=== CRASH RUN ==="
# sim_robot_final.py generates both safe and crash in __main__
# For an explicit crash capsule, use the dispatcher:
python tools/sim_robot.py --phase2 capsules_final --runs 1 --crash
CAP=$(ls -td capsules_final/capsule-* | head -n1)

echo "Compiling evidence..."
axm-compile "$CAP" shard_out/

echo ""
echo "=== VERIFY ==="
axm-verify shard shard_out/

echo ""
echo "=== TAMPER TEST ==="
python scripts/corrupt_one_byte.py "$CAP/cam_latents.bin"
set +e
axm-compile "$CAP" shard_out_fail/
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "ERROR: Expected compile to fail after corruption."
  exit 1
fi
echo "PASS: Compiler rejected corrupted latents."
