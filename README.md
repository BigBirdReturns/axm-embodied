# AXM Embodied — Flash Freeze Flight Recorder

**AXM Embodied** is a reference implementation of a *physical liability protocol* for embodied AI and robotics.

This repository demonstrates **Flash Freeze**:
- Always record **latent context** (what the model perceived).
- Only persist **high‑resolution evidence** when a Tier‑1 safety rule is violated.
- Verify evidence by **scanning disk artifacts**, not trusting logs.

Powered by the [AXM Genesis kernel](https://github.com/BigBirdReturns/axm-genesis).

## Why this exists
Robots today produce narrative logs. Narrative can lie.
Regulated systems require **physical, bounded, verifiable evidence**.

Flash Freeze makes continuous recording affordable and forensics defensible.

## Threat model (summary)
Defends against:
- Log tampering and reordering
- Offset drift between logs and evidence
- Corrupted mid‑stream bytes
- Oversized payload attacks (zip‑bomb style)
- Partial recoverable corruption

Out of scope:
- Controller‑level lies without hardware support
- Perfect durability without fsync‑capable storage

See SECURITY.md for details.

## Demo
```bash
./scripts/demo.sh
```

## Status
Reference implementation. Apache‑2.0 licensed.
