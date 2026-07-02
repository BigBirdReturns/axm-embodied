#!/usr/bin/env bash
set -euo pipefail

# Board Demo: the closed loop — beyond the flight recorder.
#
#   Drone School -> signed envelope -> Law Gate -> armed flight
#   -> physics excursion -> ESTOP + Flash Freeze -> incident shard
#   that CITES the envelope it broke -> tamper tests.
#
# Usage:
#   ./scripts/board_demo.sh
#
# Requires: pip install -e .   (axm-runtime, axm-bounds, axm-compile,
# plus axm-build/axm-verify from the axm-genesis kernel)

DEMO=demo
rm -rf "$DEMO"
mkdir -p "$DEMO"

echo "== Step 0: Keys (no default keys — ever) =="
axm-build keygen "$DEMO/keys" --name drone_school
axm-build keygen "$DEMO/keys" --name robot_unit7

echo
echo "== Step 1: Drone School — record safe training missions =="
axm-runtime record-training "$DEMO/training" --runs 3 --frames 100 --seed 7

echo
echo "== Step 2: Compile the signed safety envelope (bounds shard) =="
axm-bounds "$DEMO/training" "$DEMO/bounds_shard" --key "$DEMO/keys/drone_school.key"

echo
echo "== Step 3: Enroll the school's key in the robot's governance =="
axm-runtime enroll "$DEMO/keys/drone_school.pub" --governance "$DEMO/governance"
cp governance/local_policy.json "$DEMO/governance/"

echo
echo "== Step 4: Safe flight — armed, all frames within the envelope =="
axm-runtime fly "$DEMO/bounds_shard" "$DEMO/flight_safe" \
  --governance "$DEMO/governance" --frames 100 --seed 42

echo
echo "== Step 5: Fault flight — wheel slip at frame 50, VLA oblivious =="
set +e
axm-runtime fly "$DEMO/bounds_shard" "$DEMO/flight_fault" \
  --governance "$DEMO/governance" --frames 100 --seed 42 \
  --inject-fault --fault-at 50 --key "$DEMO/keys/robot_unit7.key"
rc=$?
set -e
if [[ "$rc" -ne 3 ]]; then
  echo "ERROR: expected exit 3 (breach + incident sealed), got $rc"
  exit 1
fi

echo
echo "== Step 6: Independent verification of the incident shard =="
axm-verify shard "$DEMO/flight_fault/incident-shard" \
  --trusted-key "$DEMO/keys/robot_unit7.pub" > /dev/null
echo "PASS: incident shard verifies (embodied@1 continuity checked)"
echo "Envelope citation:"
cat "$DEMO/flight_fault/incident-shard/ext/references@1.jsonl"

echo
echo "== Step 7: Tamper test A — corrupt the envelope, robot must not arm =="
python scripts/corrupt_one_byte.py "$DEMO/bounds_shard/content/source.txt"
set +e
axm-runtime fly "$DEMO/bounds_shard" "$DEMO/flight_tampered" \
  --governance "$DEMO/governance" --frames 10 --seed 1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "ERROR: robot armed under a tampered envelope."
  exit 1
fi
echo "PASS: Law Gate refused to arm under a tampered envelope."

echo
echo "== Step 8: Tamper test B — corrupt sealed evidence, verify must fail =="
python scripts/corrupt_one_byte.py "$DEMO/flight_fault/incident-shard/content/cam_latents.bin"
set +e
axm-verify shard "$DEMO/flight_fault/incident-shard" \
  --trusted-key "$DEMO/keys/robot_unit7.pub" > /dev/null 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "ERROR: verifier accepted corrupted evidence."
  exit 1
fi
echo "PASS: verifier rejected corrupted incident evidence."

echo
echo "== Step 9 (optional, needs network): anchor the incident's timestamp =="
set +e
axm-runtime attest-flush "$DEMO/flight_fault/attestations"
set -e

echo
echo "ALL STEPS PASSED — the loop is closed:"
echo "  training capsules -> signed envelope -> armed flight -> ESTOP"
echo "  -> Flash Freeze -> incident shard citing the envelope it broke."
