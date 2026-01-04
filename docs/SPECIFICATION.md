------

# AXM Embodied Genesis Specification

**Version:** 1.0.0
**Status:** FROZEN
**Scope:** Embodied Autonomous Systems
**Audience:** Robotics manufacturers, safety boards, auditors, regulators, systems engineers

------

## 1. Purpose

AXM Embodied Genesis defines a deterministic protocol for transforming raw robot experience into immutable, verifiable, executable knowledge.

The protocol exists to solve a problem probabilistic AI cannot solve:

**Accountability.**

Robotic systems operating in physical environments must obey constraints that are provable, auditable, and enforceable independent of model behavior.

This specification defines how those constraints are captured, compiled, verified, distributed, and enforced.

------

## 2. Core Design Principle

**Separate experience from law.**

- Experience is messy, high entropy, probabilistic.
- Law is minimal, low entropy, deterministic.

AXM enforces this separation through two phases:

| Phase   | Name    | Properties                           |
| ------- | ------- | ------------------------------------ |
| Phase A | Capsule | Raw, append-only, byte authoritative |
| Phase B | Shard   | Compiled, immutable, signed          |

No system is allowed to act on Phase A directly.

All actuation must pass through Phase B.

------

## 3. Terminology

**Capsule**
A Phase A artifact containing raw robot logs and metadata.

**Shard**
A Phase B artifact containing compiled knowledge, evidence anchors, and cryptographic integrity.

**Compiler**
Software that transforms Capsules into Shards under deterministic rules.

**Verifier**
Software that enforces the protocol invariants.

**Mounted Law**
Shards that pass verification and are authorized for actuation.

**Tier**
An epistemic strength classification for claims.

**Publisher**
An entity authorized to sign Shards.

------

## 4. Threat Model

AXM assumes:

- Models hallucinate.
- Logs are noisy.
- Sensors lie.
- Actors behave adversarially.
- Audits occur after failure.

AXM defends against:

- Post hoc log manipulation
- Probabilistic safety claims
- Cloud-only enforcement
- Undocumented behavior
- Irreproducible decisions

AXM does not attempt to:

- Predict all failures
- Eliminate uncertainty
- Replace control systems
- Replace ML models

------

## 5. Phase A: The Capsule

### 5.1 Capsule Structure

A Capsule is a directory or archive with the following required files:

```
capsule/
├── meta.json
└── events.jsonl
```

Optional files may exist but are ignored by the protocol.

### 5.2 meta.json (Normative)

```json
{
  "robot_id": "string",
  "session_id": "uuid",
  "started_at": "RFC3339 timestamp",
  "ended_at": "RFC3339 timestamp",
  "event_log_encoding": "utf-8",
  "event_log_newline": "\n"
}
```

### 5.3 events.jsonl (Byte Authority)

- events.jsonl is treated as **opaque bytes**
- No reserialization is allowed during verification
- Newlines and encoding are authoritative
- Byte offsets are measured on the raw file

The Capsule is append-only. No mutation is permitted after session end.

------

## 6. Phase B: The Shard

### 6.1 Shard Structure (Normative)

```
shard/
├── manifest.json
├── content/
├── graph/
│   ├── entities.parquet
│   ├── claims.parquet
│   └── provenance.parquet
├── evidence/
│   └── spans.parquet
├── sig/
│   ├── manifest.sig
│   └── publisher.pub
└── governance/
    ├── trust_store.json
    └── local_policy.json
```

No extra files are permitted.

------

## 7. Canonical Identity Rules

All IDs are deterministic.

### 7.1 Canonicalization

Text inputs must be canonicalized using:

1. Unicode NFKC
2. Case folding
3. Whitespace normalization
4. Control character removal

### 7.2 ID Format

```
<prefix>_base32(sha256(canonical_payload)[:15])
```

Prefixes:

| Type       | Prefix |
| ---------- | ------ |
| Entity     | e_     |
| Claim      | c_     |
| Span       | s_     |
| Provenance | p_     |

------

## 8. Graph Tables

### 8.1 entities.parquet

| Column    | Type   |
| --------- | ------ |
| entity_id | string |
| namespace | string |
| label     | string |
| type      | string |

### 8.2 claims.parquet

| Column      | Type   |
| ----------- | ------ |
| claim_id    | string |
| subject     | string |
| predicate   | string |
| object      | string |
| object_type | enum   |
| tier        | int    |

Valid object_type values:

- entity
- literal:string
- literal:integer
- literal:decimal
- literal:boolean

Valid tier values: 0–4

------

## 9. Evidence and Provenance

### 9.1 spans.parquet

| Column      | Type   |
| ----------- | ------ |
| span_id     | string |
| source_hash | string |
| byte_start  | int64  |
| byte_end    | int64  |
| text        | string |

The text field must match the exact byte slice from events.jsonl.

### 9.2 provenance.parquet

| Column        | Type   |
| ------------- | ------ |
| provenance_id | string |
| claim_id      | string |
| span_id       | string |
| source_hash   | string |
| byte_start    | int64  |
| byte_end      | int64  |

------

## 10. Compiler Contract (Normative)

A compiler must satisfy all invariants.

### 10.1 Determinism

Given identical input Capsule bytes and compiler version, the output Shard bytes must be identical.

### 10.2 Traceability

Every claim must link to one or more byte ranges in events.jsonl.

### 10.3 Objectivity

Evidence must be verbatim. No paraphrasing. No summarization.

### 10.4 Categorization

Each claim must be assigned a Tier:

| Tier | Meaning             |
| ---- | ------------------- |
| 0    | Formal invariant    |
| 1    | Safety rule         |
| 2    | Observed fact       |
| 3    | Statistical pattern |
| 4    | Hypothesis          |

------

## 11. Manifest and Integrity

### 11.1 manifest.json

```json
{
  "spec": "1.0",
  "created": "timestamp",
  "capsule_hash": "sha256",
  "merkle_root": "blake3",
  "publisher": {
    "pubkey": "hex"
  }
}
```

### 11.2 Merkle Root

Computed over all files except:

- manifest.json
- sig/*

Leaf hash:

```
BLAKE3(path + 0x00 + content)
```

------

## 12. Cryptographic Signing

- Ed25519 is required
- The manifest is signed byte-for-byte
- The public key is included in sig/publisher.pub

------

## 13. Governance

### 13.1 trust_store.json

Defines which publishers are allowed to produce actuatable law.

```json
{
  "version": "1.0",
  "allowed_keys": {
    "<pubkey_hex>": "Human readable authority"
  }
}
```

### 13.2 local_policy.json

Defines runtime enforcement constraints.

```json
{
  "max_actuation_tier": 1,
  "required_approvals": []
}
```

------

## 14. Law Gate (Runtime Rule)

A robot may actuate if and only if:

1. A matching claim exists
2. claim.tier <= max_actuation_tier
3. publisher key is trusted
4. shard verification passes
5. evidence bytes match capsule

No exceptions.

------

## 15. Query Layer

AXM exposes knowledge through SQL views.

### 15.1 mounted_law_v

```sql
SELECT * FROM claims WHERE tier <= 1
```

### 15.2 Deterministic Fallback

If no matching law exists, the robot must enter a safe state.

------

## 16. Fleet Semantics

- Shards are additive
- Conflicts are resolved by policy, not similarity
- Revocation is handled by trust_store updates
- Shards may be mounted, pinned, or unmounted

------

## 17. Conformance

A compliant implementation must:

- Produce bit-identical shards for reference inputs
- Pass axm-verify with zero warnings
- Reject unauthorized publishers
- Enforce byte-exact evidence matching

------

## 18. What AXM Is Not

- Not a model
- Not a training system
- Not a cloud service
- Not probabilistic

AXM is law.

------

## 19. Closing Statement

This specification defines the **Embodied Internet**.

It allows intelligence to scale without surrendering accountability.

It makes knowledge portable, inspectable, and enforceable.

It survives its creator.

