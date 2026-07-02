# Governance — the robot's local law

This directory is the Law Gate's ground truth. The runtime arms only when
a bounds shard verifies against a key enrolled here.

```
trust_store.json      {"trusted_publishers": ["<sha256 of .pub bytes>", ...]}
local_policy.json     {"max_actuation_tier": 0}   # Tier-0 law only
trusted_keys/         enrolled axm-hybrid1 public keys (1344 bytes each)
```

Enrollment is deliberate and auditable:

```bash
axm-runtime enroll drone_school.pub --governance governance/
```

A `.pub` file dropped into `trusted_keys/` without its fingerprint in
`trust_store.json` is ignored. An empty trust store means the robot
cannot arm at all — **no proof, no motion**.

The store ships empty: there is no default trusted publisher, exactly as
there is no default signing key.
