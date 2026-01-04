#!/usr/bin/env bash
set -e

echo "=== SAFE RUN ==="
python tools/sim_robot_final.py
echo "Residual size (safe):"
ls -lh capsules_final/*/cam_residuals.bin || true

echo "=== CRASH RUN ==="
python tools/sim_robot_final.py
echo "Compiling evidence..."
python src/axm_compile/streams.py capsules_final/* out || true

echo "=== TAMPER TEST ==="
CAP=$(ls capsules_final | head -n1)
printf '\x00' | dd of=capsules_final/$CAP/cam_latents.bin bs=1 seek=10 count=1 conv=notrunc
python src/axm_compile/streams.py capsules_final/$CAP out || echo "Tamper detected."
