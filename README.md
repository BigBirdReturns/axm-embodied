# AXM Embodied — Physical Liability Spoke

**AXM Embodied** is the physical liability spoke of the AXM ecosystem. It is the reference implementation of the [AXM Compatibility Contract](https://github.com/BigBirdReturns/axm-core).

It implements **Flash Freeze**: a forensic flight recorder for embodied AI and robotics that produces cryptographically sealed Genesis Shards proving exactly what a robot perceived, predicted, and chose at the moment of a safety event.

## What this is

Robots today produce narrative logs. Narrative can lie. A robot can log "I stopped" while physically accelerating.

AXM Embodied captures:

- **Actus Reus** — what physically happened (binary sensor streams, camera residuals)
- **Mens Rea** — what the VLA predicted and chose (latent state, action confidence distribution)

And compiles it into a post-quantum signed Genesis Shard. When the lawyers show up, you hand them that shard. Not a `.txt` file. A cryptographic artifact that `axm-verify` will accept or reject. No vendor code. No runtime access. Just the proof.

## Architecture

```
axm-genesis  ←  axm-core  ←  axm-embodied
  kernel          hub           spoke
```

This repo is the **spoke**. It owns nothing cryptographic.

```
axm-genesis (kernel)
  axm_build.*        — compiler, Merkle, signing
  axm_verify.*       — verifier, error codes, schemas

axm-core (hub)
  pulls genesis as a declared dependency
  exposes registry and tooling surface

axm-embodied (spoke)
  src/axm_embodied/compile.py      — post-run shard compiler    (axm-compile CLI)
  src/axm_embodied/streams.py      — binary stream parser, StrictJudge
  src/axm_embodied/bounds.py       — safety envelope compiler   (axm-bounds CLI)
  src/axm_embodied_core/protocol.py — binary format constants (AXLF, AXLR, AXRR)
  src/axm_embodied_core/ids.py     — identity shim → genesis hub
  tools/sim_robot_final.py         — Flash Freeze simulator
  governance/                      — trust store, local actuation policy
```

`axm-embodied` imports from `axm-core`. `axm-core` never imports `axm-embodied`.

## Flash Freeze

| Stream | File | Retention |
|--------|------|-----------|
| Hot (latents) | `cam_latents.bin` | Always — every frame, append-only |
| Cold (residuals) | `cam_residuals.bin` | Zero by default; flushed on Tier-1 trigger |

The hot stream is gap-free by design. `axm-verify` will reject any capsule with a missing frame (`E_BUFFER_DISCONTINUITY`). You cannot selectively omit failures.

**StrictJudge** scans binary artifacts directly. It does not trust log offsets. If the log says a record exists at a given offset and the binary disagrees, the binary wins. Disk is truth.

## Shard layout

```
shard/
├── manifest.json              # Merkle root, suite, publisher
├── sig/
│   ├── manifest.sig           # ML-DSA-44 (post-quantum) or Ed25519 signature
│   └── publisher.pub
├── content/
│   ├── source.txt             # events.jsonl (byte-authoritative)
│   └── cam_latents.bin        # hot stream binary — hashed as raw bytes
├── graph/
│   ├── entities.parquet
│   ├── claims.parquet         # selected_action, wheel_slip, emergency_stop ...
│   └── provenance.parquet
├── evidence/
│   └── spans.parquet
└── ext/
    └── streams@1.parquet      # stream metadata (StrictJudge results)
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

`axm-core` is pulled automatically. `blake3`, `pynacl`, and `dilithium-py` come transitively from there. Do not install them directly.

## Quickstart

```bash
# Safe run (zero residuals, hot stream only)
python tools/sim_robot_final.py

# Crash run (residuals flushed on wheel_slip + emergency_stop)
python tools/sim_robot_final.py --crash

# Board demo: safe + crash + tamper test
./scripts/board_demo.sh

# Compile a capsule into a Genesis shard
axm-compile capsules_final/capsule-<id>/ shard_out/

# Post-quantum by default (ML-DSA-44). Ed25519 legacy:
axm-compile capsules_final/capsule-<id>/ shard_out/ --legacy

# Verify the compiled shard
axm-verify shard shard_out/

# Compile a safety envelope from safe training runs
axm-bounds demo_safe/ bounds_shard/
```

## AXM Compatibility

This spoke satisfies all five requirements of the [AXM Compatibility Contract](https://github.com/BigBirdReturns/axm-core):

| Req | Description | Enforcement |
|-----|-------------|-------------|
| REQ 1 | Manifest integrity | `E_MERKLE_MISMATCH`, `E_SIG_INVALID` |
| REQ 2 | Content identity | `cam_latents.bin` in Merkle tree as raw bytes |
| REQ 3 | Lineage events | Every claim has byte-level span in `events.jsonl` |
| REQ 4 | Proof bundle | `axm-verify` with no runtime access |
| REQ 5 | Non-selective recording | `E_BUFFER_DISCONTINUITY` on frame gap |

The compiler self-verifies: `axm-compile` calls `axm-verify` internally and will not produce a shard that fails.

## Threat model

Defends against: log tampering, offset drift, mid-stream corruption, oversized payload attacks, partial recoverable corruption, selective failure omission.

Out of scope: controller-level lies without hardware support, perfect durability without fsync-capable storage.

See `SECURITY.md` and `docs/RFC-001-heavy-evidence.md`.

## License

Apache-2.0
