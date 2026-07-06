# AXM Embodied — Frame Capture v0

Event-triggered **camera frames** as cryptographically sealed physical evidence.
The camera-frame sibling of the Flash Freeze flight recorder: where Flash Freeze
captures what a VLA *perceived and chose* (latents + residuals), this captures
what a **sensor saw** (full opaque frames) around a declared trigger — a home
camera, a doorbell, a hazard cam — with the same discipline.

This is the honest first rung of the "point AXM at your Ring camera" idea:
**capture and custody, without any filtering or interpretation.** The "useful
dataset" — who/what/when — is a later, separate, bounded, human-gated annotation
layer. It is deliberately **not** in this recorder.

## What it does

```
camera ─► observe every frame ─► KEEP only a pre/post window around a trigger
          (opaque bytes)         (motion sensor / doorbell — DECLARED, never inferred)
                                     │  continuity hash chain over kept frames
                                     ▼
                              frames.bin + events.jsonl + capture_manifest.json
                                     │  FrameJudge: rescan, recompute every hash + the
                                     │  whole chain, cross-check the log (disk is truth)
                                     ▼
                              axm-compile ─► Genesis axm-hybrid1 shard
                              (frames sealed VERBATIM; streams@1 index in the Merkle tree)
                                     │
                                     ▼  axm-verify --trusted-key <oob.pub>
                                   PASS
```

## Discipline (the load-bearing parts)

- **Frames are opaque sensor bytes.** The recorder never decodes, transcodes,
  filters, classifies, or interprets them — no vision model, no OCR, no numpy.
  What the sensor emitted is what gets hashed and sealed, byte for byte
  (asserted: importing the modules pulls in no `PIL`/`cv2`/`torch`/`numpy`).
- **Event-triggered, honestly.** Frames are observed continuously but *kept* only
  in a pre/post window around an **explicit** trigger. The trigger's `reason` and
  `source` are caller-supplied (a motion sensor id, a doorbell) — a trigger is
  **never** inferred from the pixels, and an empty reason/source is refused.
- **Gaps are declared, not hidden.** Frame ids stay globally monotonic across the
  whole session, so the frames NOT kept between windows are visible in the sealed
  ids, and each window is bracketed by `capture_window_opened` /
  `capture_window_closed` log events. This is *not* continuous coverage and never
  claims to be.
- **Continuity is a hash chain.** Every kept record carries `SHA-256(payload)` and
  `chain_n = SHA256(chain_{n-1} ‖ payload_hash ‖ frame_id)`. The chain runs
  unbroken *across* the declared gaps; a removed, altered, or reordered record
  breaks it. A break is itself a finding.
- **Disk is truth.** `FrameJudge` recomputes every hash and the full chain from
  `frames.bin` and cross-checks the event log before anything is sealed. A
  tampered, truncated, or lying capsule never compiles.
- **Custody is the kernel's.** All sealing/verification is `axm_build` /
  `axm_verify`; `shard_id` is the genesis-derived `sh1_`. The spoke owns nothing
  cryptographic.
- **No false profile.** The shard declares **no** `embodied@1` profile — that
  profile asserts the VLA hot-stream continuity check over `cam_latents.bin`,
  which a camera capsule does not carry. Frame continuity is enforced by
  `FrameJudge` before sealing and pinned by the chained records inside the
  Merkle-sealed `frames.bin`. Claiming `embodied@1` here would be a false
  assertion, so it is not made.

## Evidence tier — explicit and bounded

`physical_capture`: **opaque sensor bytes within declared trigger windows only.**
Not identity. Not activity or semantic classification. Not continuous coverage.
Not platform truth. Not legal-grade provenance by itself. The tier and its limits
are sealed inside the shard (`content/capture_manifest.json`).

## Run it

```bash
python examples/frame_capture_demo.py
python -m pytest tests/test_frame_capture.py -q
```

## Live receipts (this environment)

| Check | Result |
|---|---|
| Untriggered session | **keeps nothing** (`frames.bin` = header only, no shard) |
| Trigger keeps pre+post window; ids monotonic | **yes** |
| Two triggers: gap between windows declared; chain spans it | **yes** |
| Trigger without a declared reason/source | **refused** |
| Compiled capsule → sealed `axm-hybrid1` shard | **PASS** (`sh1_95543a07…`) |
| `frames.bin` byte-identical in the sealed shard | **yes** |
| Wrong key | **fails verification** |
| Tampered payload byte | **hash mismatch — never compiles** |
| Removed record | **continuity chain broken — fatal** |
| Log disagreeing with disk | **fatal** |
| Detached verify (only shard bytes + oob pub) | **PASS** (exit 0) |
| No vision / OCR / numpy / cross-spoke import | **yes** (subprocess-isolated) |
| Test suite | **17/17** (repo 43/43) |

**Evidence tier of this slice:** event-triggered-capture-with-sealed-continuity,
proven against synthesized opaque frames + a real genesis seal/verify. Crypto is
the kernel's ML-DSA-44 hybrid. Real camera intake (RTSP/ONVIF/file drop) and any
classification layer are **not** built here — classification, when it comes, must
arrive as tiered, human-reviewed annotation over this sealed capture, never as a
silent promotion to "what happened".

## Control question

Can AXM Embodied turn event-triggered camera frames into a sealed
`physical_capture` record — opaque bytes, declared triggers, visible gaps, an
unbroken continuity chain — that verifies after the camera and the recorder are
removed, without ever interpreting, filtering, or classifying the pixels?

**v0 answer: yes** — capture and custody only; interpretation is a later,
bounded, human-gated layer.
