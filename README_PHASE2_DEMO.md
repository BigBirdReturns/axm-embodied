# AXM Phase 2: Pattern 2 Demo (Board Terminal Runbook)

Phase 2 "Heavy Evidence" using Pattern 2:

- Event log is narrative (`events.jsonl`).
- Disk artifacts are truth (`cam_latents.bin`, `cam_residuals.bin`).
- StrictJudge scans residuals directly and asserts latent offsets to build `evidence/streams.parquet`.
- Compiler routes all crypto through `axm-core` hub. This repo owns no cryptographic primitives.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Board Demo (recommended)

```bash
./scripts/board_demo.sh
```

Runs: safe baseline → crash compile → verify → corruption tamper test.

## Manual Demo

**Safe run** (residuals = 0 bytes):

```bash
python tools/sim_robot.py --phase2 demo_safe --runs 1
ls -lh demo_safe/capsule-*/cam_*.bin
```

**Crash run, compile, verify:**

```bash
python tools/sim_robot.py --phase2 demo_crash --runs 1 --crash
axm-compile demo_crash/capsule-*/ shard_out/
axm-verify shard shard_out/
```

**Corruption test:**

```bash
python scripts/corrupt_one_byte.py demo_crash/capsule-*/cam_latents.bin
axm-compile demo_crash/capsule-*/ shard_out_fail/
# Expected: FATAL abort — StrictJudge detects offset drift
```

## Cryptographic suites

```bash
# Default: post-quantum ML-DSA-44 (FIPS 204)
axm-compile <capsule>/ <out>/

# Legacy Ed25519
axm-compile <capsule>/ <out>/ --legacy

# Reproducible gold shard (canonical key + timestamp, Ed25519)
axm-compile <capsule>/ <out>/ --gold
```
