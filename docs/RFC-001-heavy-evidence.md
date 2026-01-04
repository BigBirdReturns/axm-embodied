# RFC-001: Heavy Evidence and Binary Anchoring (Flash Freeze)

## Design Principle

This protocol assumes:
- probabilistic models
- imperfect sensors
- adversarial environments

It does not attempt to correct these.

Instead, it ensures that when a safety boundary is crossed, the physical reality of that moment is preserved in a form that is:
- discoverable
- tamper-evident
- mathematically verifiable

## Non-Goals

- This protocol does not define perception models.
- It does not define planning or control policies.
- It does not attempt to interpret sensor data semantically.

Its sole purpose is to **anchor physical evidence to decision time in a provable, bounded-cost manner**.



Status: Draft  
Target: AXM v2.0

## Problem

Text-only logs can misrepresent physical reality. A robot can log “I stopped” while physically accelerating. AXM v2.0 must anchor high-bandwidth sensor evidence (video, lidar) to the claim graph without storing continuous raw streams.

## Flash Freeze Architecture

AXM splits sensor evidence into two streams with distinct retention policies.

### Hot stream (Latents)

- Content: fixed-width, low-cost “concept” tokens (quantized latents)
- Retention: always recorded (100 percent history)
- Purpose: fast, low-compute verification and indexing of what the system perceived
- Format: fixed-width binary (`cam_latents.bin`) with deterministic record headers

### Cold stream (Residuals)

- Content: high-fidelity evidence blobs (raw video, lidar point clouds)
- Retention: zero by default
- Trigger: only flushed to disk when a Tier 1 safety event occurs (pre and post window)
- Format: variable-width binary (`cam_residuals.bin`) with deterministic record headers

## Pattern 2 Decision

Disk is truth.

- The event log provides narrative timing (frame_id for events).
- The judge discovers residuals by scanning `cam_residuals.bin` and validating record headers.
- The join key between narrative and evidence is `frame_id`.

## Evidence output

The compiler emits `evidence/streams.parquet` with:

- frame_id
- stream (latents or residuals)
- file
- offset
- length
- status
- content_hash
