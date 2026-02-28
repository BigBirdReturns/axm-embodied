# Changelog

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
