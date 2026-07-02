# AXM Embodied — Physical Liability Spoke

**AXM Embodied** is the physical liability spoke of the AXM ecosystem, built on
the [axm-genesis](https://github.com/BigBirdReturns/axm-genesis) v1 kernel.

It implements two layers:

1. **Flash Freeze** — a forensic flight recorder for embodied AI and robotics
   that produces cryptographically sealed Genesis Shards proving exactly what a
   robot perceived, predicted, and chose at the moment of a safety event.
2. **The Shadow Runtime** — enforcement of a *signed* safety envelope, in the
   loop. The recorder proves what happened; the runtime acts on the proof in
   real time: it arms only under governance-trusted, verifier-clean bounds, it
   kills motors the instant physics leaves the envelope, and it seals the
   incident into a shard that cryptographically cites the exact law it broke.

## What this is

Robots today produce narrative logs. Narrative can lie. A robot can log
"I stopped" while physically accelerating.

AXM Embodied captures:

- **Actus Reus** — what physically happened (binary sensor streams, camera residuals)
- **Mens Rea** — what the VLA predicted and chose (latent state, action confidence distribution)

And compiles it into a post-quantum-hybrid signed Genesis Shard. When the
lawyers show up, you hand them that shard. Not a `.txt` file. A cryptographic
artifact that `axm-verify` will accept or reject. No vendor code. No runtime
access. Just the proof.

Beyond the recorder, the loop is closed:

```
 Drone School                    Law Gate                    Court / Insurer
 safe capsules ──► bounds shard ──► governance check ──► ARMED
                   (signed law)      no proof, no motion     │
                        ▲                                    ▼
                        │ cites                    per-frame guard:
                        │                          latent L∞ vs signed bound
                 incident shard ◄── Flash Freeze ◄── ESTOP on breach
```

Every incident shard's `ext/references@1.jsonl` names the envelope shard id it
was recorded under, so the forensic chain runs unbroken:
**training capsules → signed envelope → armed flight → sealed incident.**

## Architecture

```
axm-genesis  ←  axm-embodied
  kernel           spoke
```

This repo is the **spoke**. It owns nothing cryptographic.

```
axm-genesis (kernel)
  axm_build.*        — compiler, Merkle, axm-hybrid1 signing, canonical JSONL
  axm_verify.*       — verifier, error codes, profiles (embodied@1)

axm-embodied (spoke)
  src/axm_embodied/recorder.py     — Flash Freeze recorder (library)
  src/axm_embodied/streams.py      — binary stream parser, StrictJudge
  src/axm_embodied/compile.py      — capsule -> shard compiler  (axm-compile)
  src/axm_embodied/bounds.py       — safety envelope compiler   (axm-bounds)
  src/axm_embodied/envelope.py     — verified envelope loader
  src/axm_embodied/gate.py         — Law Gate: governance-aware arming
  src/axm_embodied/runtime.py      — Shadow Runtime: per-frame enforcement
  src/axm_embodied/runtime_cli.py  — axm-runtime (record-training/enroll/fly)
  src/axm_embodied/sim.py          — mission simulator (VLA + sensor stand-in)
  src/axm_embodied_core/           — protocol constants, identity shim
  governance/                      — trust store, local actuation policy
  tools/sim_robot_final.py         — capsule generator harness
```

`axm-embodied` imports from `axm-genesis`. The kernel never imports the spoke.
The binary stream format and the continuity check are frozen in the kernel's
profile document [`spec/profiles/embodied@1.md`](https://github.com/BigBirdReturns/axm-genesis/blob/main/spec/profiles/embodied%401.md);
every compiled shard declares `"embodied@1"` so any conforming verifier runs
the gap check.

## Flash Freeze

| Stream | File | Retention |
|--------|------|-----------|
| Hot (latents) | `cam_latents.bin` | Always — every frame, append-only, fsync'd |
| Cold (residuals) | `cam_residuals.bin` | Zero by default; pre-window ring buffer flushed on Tier-1 trigger |

The hot stream is gap-free by design. `axm-verify` will reject any shard with
a missing frame (`E_BUFFER_DISCONTINUITY`). You cannot selectively omit
failures.

**StrictJudge** scans binary artifacts directly. It does not trust log
offsets. If the log says a record exists at a given offset and the binary
disagrees, the binary wins. Disk is truth.

## The Shadow Runtime

Fail-closed doctrine, mechanically enforced:

- **No proof, no motion.** The runtime arms only on a `Clearance` from the Law
  Gate: the bounds shard must verify (Merkle + hybrid signature + canonical
  tables + profile checks) against a key *enrolled in the robot's own
  governance directory* — never against the shard's own key.
- **No signed bound, no actuation.** An action class the envelope doesn't
  cover is forbidden motion, not a free pass. Non-finite sensor values ESTOP.
- **Breach ⇒ ESTOP + Flash Freeze.** Motors die on the breach frame, the
  residual pre-window hits disk, recording continues gap-free, and the sealed
  incident shard cites the envelope shard id via `ext/references@1`.

## Shard layout (spec/v1)

```
shard/
├── manifest.json              # Merkle root, suite, publisher, profiles, sources
├── sig/
│   ├── manifest.sig           # axm-hybrid1 (Ed25519 + ML-DSA-44), 2484 bytes
│   └── publisher.pub          # 1344 bytes
├── content/
│   ├── source.txt             # events.jsonl (byte-authoritative)
│   ├── cam_latents.bin        # hot stream — sealed as a Merkle leaf
│   └── cam_residuals.bin      # cold stream (present when Flash Freeze fired)
├── graph/
│   ├── entities.jsonl         # canonical JSONL core tables
│   ├── claims.jsonl           # selected_action, breached_envelope, ...
│   └── provenance.jsonl
├── evidence/
│   └── spans.jsonl
└── ext/
    ├── streams@1.jsonl        # StrictJudge byte-level stream index
    └── references@1.jsonl     # incident -> envelope citation
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

`axm-genesis` is pulled automatically (with an ML-DSA-44 backend). `blake3`
and `pynacl` come transitively from it. Do not install them directly.

## Quickstart — the closed loop

```bash
# The whole story in one script: keys -> training -> signed envelope ->
# enrollment -> safe flight -> fault flight -> incident shard -> tamper tests
./scripts/board_demo.sh
```

Or by hand:

```bash
# 0. Keys. There are no default keys.
axm-build keygen keys --name drone_school
axm-build keygen keys --name robot_unit7

# 1. Drone School: record safe training missions
axm-runtime record-training training/ --runs 3

# 2. Compile the signed safety envelope
axm-bounds training/ bounds_shard/ --key keys/drone_school.key

# 3. Enroll the publisher in the robot's governance (Law Gate trust store)
axm-runtime enroll keys/drone_school.pub --governance governance/

# 4. Fly. Clean mission: exit 0, cold stream stays empty.
axm-runtime fly bounds_shard/ flight/ --governance governance/

# 5. Fly with an injected physics excursion: ESTOP at the fault frame,
#    Flash Freeze, incident shard citing the envelope. Exit 3.
axm-runtime fly bounds_shard/ flight/ --governance governance/ \
    --inject-fault --key keys/robot_unit7.key

# 6. Anyone can verify the incident — no vendor code, no runtime access:
axm-verify shard flight/incident-shard --trusted-key keys/robot_unit7.pub

# 7. Compile any capsule post-hoc (the original flight-recorder path):
axm-compile flight/capsule-*/ shard_out/ --key keys/robot_unit7.key
```

## AXM Compatibility

This spoke targets the frozen surface of the genesis v1 kernel
(see the kernel's `COMPATIBILITY.md`):

| Guarantee | Enforcement |
|-----------|-------------|
| Manifest integrity | `E_MERKLE_MISMATCH`, `E_SIG_INVALID` |
| Content identity | binary streams in the `sources` bijection, hashed as raw bytes |
| Lineage events | every claim has a byte-level span in `events.jsonl` |
| Proof bundle | `axm-verify` with no runtime access |
| Non-selective recording | profile `embodied@1`: `E_BUFFER_DISCONTINUITY` on any frame gap |
| Envelope lineage | `ext/references@1` from incident shard to envelope shard id |

The compiler self-verifies: the kernel will not emit a shard that fails its
own verifier, including the `embodied@1` continuity check.

## Threat model

Defends against: log tampering, offset drift, mid-stream corruption, oversized
payload attacks, partial recoverable corruption, selective failure omission,
forged or manually widened safety envelopes (unsigned law never arms the
robot), post-hoc denial of the envelope in force (incidents cite it by id).

Out of scope: controller-level lies without hardware support, perfect
durability without fsync-capable storage, a compromised governance directory
(if the attacker can enroll keys on the robot, they are the operator).

See `docs/RFC-001-heavy-evidence.md` and the kernel's
`spec/profiles/embodied@1.md`.

## License

Apache-2.0
