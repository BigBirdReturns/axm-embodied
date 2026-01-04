# AXM Phase 2: Pattern 2 Demo (Board Terminal Runbook)

This repo contains the reference implementation of Phase 2 "Heavy Evidence" using Pattern 2:

- Event log is narrative (`events.jsonl`).
- Disk artifacts are truth (`cam_latents.bin`, `cam_residuals.bin`).
- The compiler scans residuals and asserts latent offsets to build `evidence/streams.parquet`.

## Quickstart

Create a venv and install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Run the board demo:

```bash
./scripts/board_demo.sh
```

## Manual Demo

Safe run:

```bash
python tools/sim_robot.py --phase2 demo_safe --runs 1
ls -lh demo_safe/capsule-*/cam_*.bin
```

Crash run and compile:

```bash
python tools/sim_robot.py --phase2 demo_crash --runs 1 --crash
axm-compile demo_crash/capsule-* shard_out
axm-verify shard_out
```

Corruption test:

```bash
python scripts/corrupt_one_byte.py demo_crash/capsule-*/cam_latents.bin
axm-compile demo_crash/capsule-* shard_out_fail
```
