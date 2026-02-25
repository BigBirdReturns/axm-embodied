# Release v1.2.0 — Hub-and-Spoke Migration

Built: 2026-02-24T00:00:00Z

## What changed

**Architecture**
- `axm-embodied` is now a pure physical liability spoke. It owns no cryptographic primitives.
- All crypto (blake3, ML-DSA-44, Ed25519, Merkle) routes through `axm-core` hub via transitive dependency.
- `pynacl`, `blake3`, `dilithium-py` removed from `pyproject.toml`.

**Packages deleted**
- `src/axm_compile/` — removed. `streams.py` rescued to `src/axm_embodied/streams.py`.
- `src/axm_verify/` — removed. Governance-aware trust resolution stays in `governance/` layer.

**New / updated files**
- `src/axm_embodied/streams.py` — StrictJudge and binary stream parser (unchanged behavior, new home)
- `src/axm_core/ids.py` — identity shim: `entity_id`/`claim_id` delegate to genesis hub; `span_id`/`prov_id` stay local (no genesis equivalent)
- `src/axm_embodied/compile.py` — installed as `axm-compile` CLI; full Phase 2 compiler with `--suite`, `--legacy`, `--gold` flags

## Identity safety

Unicode diff performed before migration: NFKC (embodied) vs NFC (core) canonicalize diverge only on ligature/composed-form edge cases not present in ASCII telemetry. All historical shard IDs valid. No recompile required.

## Cryptographic suites

| Suite | Flag | Status |
|-------|------|--------|
| `axm-blake3-mldsa44` | default | Post-quantum, FIPS 204 |
| `ed25519` | `--legacy` | Backward compatible |

## Demo contract

- Safe run produces `cam_residuals.bin` of 0 bytes.
- Crash run records exactly the configured pre/post windows (default: 2s each).
- Residuals discovered via binary scan, not JSON offsets.
- Any drift or corruption aborts compilation with FATAL.

---

# Release Candidate 2.0 (Gold Master) — archived

Built: 2026-01-04T02:35:33Z

Included: Phase 2 Pattern 2 implementation, StrictJudge, streams evidence, board demo.
Superseded by v1.2.0 Hub-and-Spoke migration above.
