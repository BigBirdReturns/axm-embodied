# RFC 0001: Post-Quantum Cryptographic Suite

> **Status: HISTORICAL / SUPERSEDED.** The `axm-blake3-mldsa44` suite proposed here was retired by the axm-genesis v1 reset (RFC 0002) in favor of the single hybrid suite `axm-hybrid1` (Ed25519 ‖ ML-DSA-44). Kept for provenance. <!-- drift-ok: historical pre-reset RFC; suite retired by the v1 reset -->

## Summary
Add axm-blake3-mldsa44 suite using ML-DSA-44 (FIPS 204) signatures, domain-separated BLAKE3 Merkle trees, and RFC 6962 odd-leaf promotion. Existing Ed25519 shards continue to verify unchanged. <!-- drift-ok: historical pre-reset RFC; suite retired by the v1 reset -->

## Motivation
Ed25519 is vulnerable to quantum attacks. NIST standardized ML-DSA-44 as a post-quantum signature. AXM shards are designed to last decades; adopting quantum-safe signatures now avoids forced migration.

## Specification
manifest gains optional "suite" field. When absent, defaults to "ed25519" (backward compatible).

axm-blake3-mldsa44 primitives: <!-- drift-ok: historical pre-reset RFC; suite retired by the v1 reset -->
- Signature: ML-DSA-44 (FIPS 204), deterministic. pk=1312B, sig=2420B, sk=2528B
- Leaf: BLAKE3(0x00 || relpath || 0x00 || bytes) 
- Node: BLAKE3(0x01 || left || right)
- Odd leaf: promote unchanged (RFC 6962, CVE-2012-2459 safe)
- Empty root: BLAKE3(0x01) = 48fc721f...

## Backward Compatibility
v1.0 shards (no suite field) default to ed25519. Gold shard never regenerated.
