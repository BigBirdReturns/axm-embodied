# Changelog

## [2.0.0] - 2026-07-02

Beyond the flight recorder: the spoke now *enforces* the proof, not just
records it.

### Added
- **Shadow Runtime** (`src/axm_embodied/runtime.py`) — per-frame guard
  between perception and actuation. Compares live latent L∞ against the
  signed envelope bound for the selected action class; on breach: ESTOP,
  Flash Freeze trigger, gap-free recording continues, incident sealed.
  Fail-closed: uncovered action classes and non-finite sensor values ESTOP.
- **Law Gate** (`src/axm_embodied/gate.py`) — governance-aware arming.
  "No proof, no motion": the runtime arms only when the bounds shard
  verifies against a key enrolled in `governance/trusted_keys/` AND
  fingerprinted in `trust_store.json`, and its constraints sit within
  `local_policy.json`'s `max_actuation_tier`. `enroll_key()` is the only
  sanctioned enrollment path.
- **SafetyEnvelope** (`src/axm_embodied/envelope.py`) — the runtime's view
  of a bounds shard. Constructible only from a shard that just passed full
  kernel verification against an out-of-band trust anchor.
- **CapsuleRecorder** (`src/axm_embodied/recorder.py`) — the Flash Freeze
  recorder extracted from the simulator into a library, so it can sit
  inside a real control loop. Hot stream (gap-free, fsync'd), cold-stream
  ring buffer (pre/post windows), events.jsonl, capsule lifecycle.
- **axm-runtime CLI** (`record-training` / `enroll` / `fly`). `fly` exit
  codes: 0 clean flight, 3 breach (incident sealed), 1 refused to arm.
- **Envelope lineage**: incident shards cite the envelope shard id via
  `ext/references@1.jsonl` (`relation_type: cites`), closing the chain
  training capsules → signed envelope → armed flight → sealed incident.
- Mission simulator (`src/axm_embodied/sim.py`): physically plausible
  float32 latents (safe missions stay inside the learned envelope; the
  injected fault leaves it) instead of raw entropy. The demo fault is a
  physics excursion the VLA confidently ignores — the narrative log says
  `maintain_speed`, the disk says otherwise.

### Changed
- **Migrated to the axm-genesis v1 kernel** (v1.0.0rc1, RFC 0002 reset):
  - Suite is `axm-hybrid1` (Ed25519 + ML-DSA-44); the `--legacy`/`--gold`
    Ed25519-only paths are gone.
  - Core tables are canonical JSONL; `ext/streams@1.parquet` is now
    `ext/streams@1.jsonl`. pandas/pyarrow dependencies dropped.
  - Shards declare the frozen kernel profile `"embodied@1"`; any
    conforming verifier runs the hot-stream continuity check.
  - Binary streams are sealed natively by the kernel compiler
    (`CompilerConfig.extra_content` + manifest `sources` bijection); the
    two-pass inject-and-reseal hack is deleted.
  - `cam_residuals.bin` is now also sealed in `content/` when the cold
    stream flushed (it was previously left out of the shard entirely).
- **No default signing keys.** `axm-compile` and `axm-bounds` require
  `--key` (or `AXM_SIGNING_KEY_HEX`), mirroring the kernel's discipline;
  the committed canonical demo seed is gone. `governance/trust_store.json`
  ships empty — an un-provisioned robot cannot arm.
- `axm_embodied.streams.compile_streams_evidence` (parquet writer) is now
  `build_streams_evidence` (returns rows for the kernel to encode).
- `tools/sim_robot_final.py` is a thin harness over the recorder library;
  default run produces one safe session (use `--both` for the old
  behavior). `tools/sim_robot.py` removed.
- Dependency: `axm-core` pin replaced by a direct `axm-genesis[mldsa-compat]`
  pin (the hub has not yet migrated to the v1 kernel; re-point through the
  hub when it does).

### Removed
- Committed demo artifacts (`capsules_final/`, `demo_safe/`, `demo_crash/`)
  and `README_PHASE2_DEMO.md`; `./scripts/board_demo.sh` now regenerates
  the full closed-loop story (including two tamper tests) from nothing.

## [1.4.0] - 2026-02-25
### Added
- `src/axm_embodied/bounds.py` — Bounds Compiler (installed as `axm-bounds`).
  Compiles simulation-derived safety envelope into a signed Genesis Shard.
  Calculates L∞ norm deltas per action class, establishes 99th percentile
  envelope with 1.1× safety margin, emits Tier-0 constraints.
- `tools/compile_bounds.py` — thin alias to `axm_embodied.bounds`.

### Changed
- `src/axm_embodied/compile.py` — now delegates all shard construction to
  `axm_build.compiler_generic.compile_generic_shard`. This is the only path
  that produces a genesis-verifiable shard. Manifest schema, Parquet types,
  and Merkle computation are no longer reimplemented in the spoke.
- Two-pass compilation: cam_latents.bin is injected into content/ and the
  shard is resealed after the genesis compiler runs, making it a proper
  Merkle leaf subject to REQ 5 continuity checks.

## [1.2.0] - 2026-02-24
### Changed
- Hub-and-spoke migration complete. axm-embodied is now a pure physical
  liability spoke. All crypto (blake3, ML-DSA-44, Ed25519, Merkle) routes
  through axm-core hub via transitive dependency.
- Deleted: src/axm_compile/, src/axm_verify/ (vendored copies).
- Rescued: streams.py → src/axm_embodied/streams.py.
- Added: src/axm_embodied_core/ (protocol.py, ids.py) — spoke-local constants
  and identity functions. entity_id/claim_id delegate to genesis hub.

## [1.1.0] - 2026-02-22
### Added
- Mens Rea patch: action distribution captured on every frame.
  selected_action (Tier 1) and considered_action (Tier 2) claims
  emitted regardless of event type.

## [1.0.0]
- Initial Flash Freeze implementation.
- Binary stream recorder: cam_latents.bin (always-on) + cam_residuals.bin
  (Tier-1 triggered).
- StrictJudge: scans binary files directly, never trusts log offsets.
- Law Gate: governance-aware actuation policy enforcement.
