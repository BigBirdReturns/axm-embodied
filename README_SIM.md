# Capsule Simulators

Two simulators. Use the right one for your phase.

## Phase 2 (current): `tools/sim_robot_final.py`

Generates binary capsules with latent and residual streams.

**Direct:**

```bash
# Safe run (cam_residuals.bin = 0 bytes)
python tools/sim_robot_final.py

# Edit crash=True in __main__ for a crash run, or use sim_robot.py flags
```

**Via `sim_robot.py` dispatcher:**

```bash
# Safe
python tools/sim_robot.py --phase2 <out_dir> --runs 1

# Crash (triggers Flash Freeze at frame 50)
python tools/sim_robot.py --phase2 <out_dir> --runs 1 --crash
```

Each capsule contains:

| File | Contents |
|------|----------|
| `meta.json` | Session metadata |
| `events.jsonl` | Narrative event log (byte-authoritative) |
| `cam_latents.bin` | Fixed-width latent vectors, every frame, AXLF magic |
| `cam_residuals.bin` | Raw sensor blobs, only frames in trigger window |

Feed capsules into the compiler:

```bash
axm-compile <capsule_dir>/ <shard_out>/
```

## Phase 1 (legacy): `tools/sim_robot.py` (standalone)

Generates Phase A capsules with `meta.json` and `events.jsonl` only. No binary streams.

```bash
python tools/sim_robot.py <out_dir> <runs>
# Example: python tools/sim_robot.py my_runs 10
```

Phase 1 capsules feed into the legacy `axm-compile` pipeline. For new work, use Phase 2.
