# AXM Embodied — Physical Liability Spoke

**AXM Embodied** is the physical liability spoke of the [AXM ecosystem](https://github.com/BigBirdReturns/axm-core).

It implements **Flash Freeze**: a forensic flight recorder for embodied AI and robotics that produces post-quantum secured Genesis Shards proving exactly what a robot perceived, predicted, and did at the moment of a safety event.

## What this is

Robots today produce narrative logs. Narrative can lie. A robot can log "I stopped" while physically accelerating.

AXM Embodied captures:

- **Actus Reus** — what physically happened (binary streams, sensor residuals)
- **Mens Rea** — what the VLA predicted and chose (latent state, action confidence)

And compiles it into a mathematically un-fakeable Genesis Shard. When the lawyers show up, you hand them that. Not a `.txt` file.

## Hub-and-Spoke Architecture

This repo is the **physical liability spoke**. It does not own cryptography.

```
axm-core (hub)
├── Genesis crypto kernel (blake3, ML-DSA-44, Ed25519, Merkle)
├── Canonical identity (entity_id, claim_id)
└── Compiler contract

axm-embodied (spoke)
├── Flash Freeze simulator     tools/sim_robot_final.py
├── Binary stream parser       src/axm_embodied/streams.py
├── StrictJudge evidence scan  src/axm_embodied/streams.py
├── Post-run shard compiler    src/axm_embodied/compile.py  (axm-compile CLI)
└── Governance policy layer    governance/
```

`axm-embodied` calls `axm-core`. `axm-core` never imports `axm-embodied`.

## Flash Freeze

Always record **latent context**. Only persist **high-resolution evidence** when a Tier-1 safety rule fires.

| Stream | File | Retention |
|--------|------|-----------|
| Hot (latents) | `cam_latents.bin` | Always — every frame |
| Cold (residuals) | `cam_residuals.bin` | Zero by default; flushed on trigger with pre/post window |

**StrictJudge** scans binary artifacts directly. It does not trust log offsets. Disk is truth. If the log and the binary disagree, the binary wins.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

`axm-core` is pulled automatically. `pynacl`, `blake3`, and `dilithium-py` come transitively from there — do not install them directly.

## Quickstart

```bash
# Safe run (zero residuals)
python tools/sim_robot_final.py

# Board demo: safe + crash + corruption tamper test
./scripts/board_demo.sh

# Compile a capsule directory into a Genesis shard
axm-compile capsules_final/capsule-<id>/ shard_out/

# Post-quantum by default. Ed25519 legacy:
axm-compile capsules_final/capsule-<id>/ shard_out/ --legacy

# Verify
axm-verify shard shard_out/
```

## Threat model

Defends against: log tampering, offset drift, mid-stream corruption, oversized payload attacks, partial recoverable corruption.

Out of scope: controller-level lies without hardware support, perfect durability without fsync-capable storage.

See `SECURITY.md` and `docs/RFC-001-heavy-evidence.md`.

## Status

v1.2.0 — Hub-and-Spoke migration complete. Apache-2.0 licensed.
