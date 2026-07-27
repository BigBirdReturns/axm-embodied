# RODOH embodied action-session evidence

## Object classification

`axm-embodied-action-session/1` is a physical-session custody object. It links room-scale tracking and guardian observations, sensor captures, a provisional Unity action execution candidate, and the later Arc-owned `axm-action-receipt/1`. It does not resolve combat, mutate a campaign, or reinterpret a physical stop as a game failure.

The actors are:

- **Arc**, which owns cartridge identity, action law, deterministic replay, accepted outcome, and campaign consequence;
- **Unity and RODOH World**, which own input sampling, spatial presentation, animation, camera, VFX, audio, haptics, and the provisional trace candidate;
- **axm-embodied**, which owns physical observation custody, capture identity, event ordering, tamper evidence, and later linkage to the Arc receipt;
- **axm-genesis**, which may later preserve the compiled shard and verify its custody chain without inheriting combat authority.

## Mechanism

One session directory contains:

```text
session/
  manifest.json
  events.jsonl
```

The manifest fixes:

- session identity;
- exact `cart1_` cartridge digest;
- exact `actspec1_` action-spec digest;
- physical device identity;
- optional `unityjob1_` scene-job digest;
- event count and hash-chain head;
- provisional candidate and accepted receipt attachment digests;
- explicit authority boundaries.

Every event contains a contiguous sequence number, the previous event digest, and a digest over canonical JSON plus the previous digest. The event journal is append-only. Verification refuses missing, reordered, modified, duplicate, or inserted events, as well as a manifest that does not name the exact journal head.

## Event classes

### `session_started`

Records the exact cartridge, action spec, device, and Unity scene job that opened the physical session.

### `physical_session_stopped`

Consumes `rodoh-embodied-action-observation/1` emitted by the Unity `ActionSafetyGate`. The accepted observation reasons include tracking discontinuity, non-finite tracking, guardian clearance, unknown guardian state when required, vertical-envelope violation, and application focus loss.

The event always carries:

```json
{
  "campaignEffect": null
}
```

A physical stop can pause or end the local presentation. It cannot declare an Arc success, partial, or failure outcome.

### `capture_recorded`

Records a path, media type, byte length, SHA-256, stream identity, and optional action tick. Camera, depth, audio, IMU, hand, room, or telemetry captures may be linked. A capture has no semantic authority merely because it is authentic.

### `action_candidate_attached`

Consumes the Unity `rodoh-action-execution-candidate/1`. The journal verifies:

- exact cartridge and action-spec identity;
- explicit `Arc replay required` authority;
- bounded run-length trace structure;
- signed-axis input law;
- four-button mask;
- exact expansion from compressed runs to `totalTicks`;
- one candidate per session.

The candidate may expose a provisional outcome for responsive presentation. The journal records that value separately from `acceptedOutcome`, which remains `null` until Arc replay.

### `arc_receipt_attached`

Consumes a verified `axm-action-receipt/1` after the candidate exists. The receipt must match the session cartridge and action-spec identities and expose success, partial, or failure. The attachment makes the accepted outcome legible, but axm-embodied still does not perform the campaign mutation.

## Receipts and evidence tier

The evidence ledger is:

- **Evidence tier:** cryptographically hash-chained local source evidence with exact external attachment digests;
- **Venue:** the holder's physical-session estate and later Genesis custody;
- **Target:** continuity between physical execution, Unity presentation, deterministic Arc replay, and campaign record;
- **Upside:** a guardian stop, tracking fault, camera frame, provisional result, and accepted action receipt can be audited together without conflating their authority;
- **Downside:** physical sensor truth remains device- and calibration-bounded, while the provisional Unity trace remains unaccepted until Arc replay;
- **Failure mode:** missing capture bytes, a corrupted journal, mismatched action identity, a Unity candidate claiming final authority, or an Arc receipt attached to the wrong session.

## CLI

Initialize a session:

```bash
python -m axm_embodied.action_session init local/action-sessions/frog-pit-001 \
  --session-id frog-pit-001 \
  --arc-digest cart1_<64-hex> \
  --action-spec-digest actspec1_<64-hex> \
  --device-id quest-3-left-room \
  --job-digest unityjob1_<64-hex>
```

Append a Unity safety observation:

```bash
python -m axm_embodied.action_session append-observation \
  local/action-sessions/frog-pit-001 \
  action-safety-20260726-120000-000.json
```

Attach the provisional Unity candidate:

```bash
python -m axm_embodied.action_session attach-candidate \
  local/action-sessions/frog-pit-001 \
  latest-action-candidate.json
```

Attach the later Arc receipt:

```bash
python -m axm_embodied.action_session attach-receipt \
  local/action-sessions/frog-pit-001 \
  accepted-action-receipt.json
```

Verify the journal:

```bash
python -m axm_embodied.action_session verify local/action-sessions/frog-pit-001
```

Project a custody shard:

```bash
python -m axm_embodied.action_session shard \
  local/action-sessions/frog-pit-001 \
  --output local/action-sessions/frog-pit-001/genesis-shard.json
```

The shard summarizes the exact session head and attachment digests. It does not claim campaign mutation and does not replace the eventual Genesis compiler contract.

## Embodied-AR-Lab integration

The Unity action estate writes to the existing scene-job directory:

```text
local/scene-jobs/<job-id>/
  input/
    action.unity-action-spec.json
    action.scene-job.json
  logs/
  output/
    validation.json
    local-run.json
    latest-action-candidate.json
```

The physical action-session directory should be a sibling rather than an overlay:

```text
local/action-sessions/<session-id>/
  manifest.json
  events.jsonl
  streams/
  attachments/
```

This separation prevents a Unity rebuild or scene-job cleanup from deleting the evidentiary record. The session manifest binds the exact `unityjob1_` digest when the presentation job exists.

The Unity `ActionSafetyGate` should call the action-session CLI or a thin Python service after writing each observation. The action candidate should be attached at local encounter completion or controlled stop. Arc replay may happen immediately on the same machine, after export to the browser player, or later on another compatible holder. The accepted receipt joins the same journal whenever it becomes available.

## Acceptance

The module is accepted when tests prove:

- physical observations cannot claim success, partial, or failure;
- physical stops carry no campaign effect;
- trace compression expands exactly;
- candidate identity must match the session;
- the Arc receipt cannot precede the candidate;
- candidate and receipt attachments are single-assignment;
- receipt identity must match the session;
- modified journal bytes break verification;
- captures remain evidence without semantic authority;
- a Genesis-facing shard claims an accepted action outcome only after an Arc receipt exists;
- the shard never claims campaign mutation.

The control question is whether a later auditor can distinguish what the player physically did, what Unity presented, what Arc deterministically accepted, and what the campaign eventually changed without trusting any one layer to speak for all four.
