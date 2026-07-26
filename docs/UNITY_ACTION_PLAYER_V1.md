# Unity action player v1

## Classification and authority

The Unity action player is a compatible physical presentation and control adapter for the AXM action runtime. It is not a second combat engine and it does not own campaign consequences.

The actors remain separate:

- `axm-arc` owns cartridge law, `axm-action-spec/1`, the 30 Hz fixed-step action simulation, receipt verification, and campaign mutation.
- the Unity player owns tracked input sampling, interpolation, rendering, camera composition, AR placement, accessibility, and local device adaptation.
- `axm-embodied` owns physical sensor custody, anchor and pose evidence, safety-envelope enforcement where physical movement is involved, and incident sealing.
- the holder owns the exact cartridge, action receipt, embodied evidence capsule, and any local presentation profile.

A Unity frame may display an Arc-authored result. It may not invent damage, enemy state, objective completion, or a reward. A physical tracking sample may explain how the player acted. It may not silently rewrite the action trace.

## Existing Embodied-AR-Lab substrate

The first integration target is the existing Unity 6000.0.66f2 Embodied-AR-Lab project. That project already proves the expensive platform seams needed by the player:

- camera feed exposure;
- detected-plane exposure;
- tap-to-place behavior;
- anchor continuity;
- edit-mode and play-mode test execution;
- deterministic scene compilation and standalone smoke receipts.

The action player therefore begins above those seams. It does not create a replacement AR bootstrap, camera stack, plane manager, anchor store, or scene compiler.

## Runtime topology

```text
Arc cartridge
  -> compileActionEncounter
  -> axm-action-spec/1
  -> Arc action bridge sidecar
       <-> quantized Unity input batches
       -> authoritative state snapshots and presentation events
       -> axm-action-receipt/1
  -> ordinary Arc cycle consequence

Unity camera, planes, anchors, controller and hand observations
  -> axm-unity-action-frame/1 stream
  -> optional Flash Freeze capsule
  -> Genesis Shard under embodied@1 when an evidence trigger fires
```

The sidecar uses Arc's existing TypeScript authority directly. This is the shortest route to a real Unity player without creating a cross-language combat fork. The Unity package is designed so that the transport may later be replaced by an accepted WebAssembly or conformance-proven C# mirror without changing scene, control, or evidence interfaces.

## Bridge protocol

The transport format is `axm-action-bridge/1`. The reference carrier is newline-delimited JSON over a local or LAN TCP socket. TCP is used because Unity 6, Windows, Android, and Quest can support it without a browser, cloud account, or third-party WebSocket package.

Every message contains:

```json
{
  "format": "axm-action-bridge/1",
  "sessionId": "opaque holder-generated id",
  "sequence": 17,
  "kind": "input"
}
```

The bounded message kinds are:

| Kind | Direction | Purpose |
|---|---|---|
| `hello` | Unity to Arc | Negotiate protocol, action-runtime version, tick rate, and maximum input batch. |
| `hello-accepted` | Arc to Unity | Bind the exact authority version and limits. |
| `open` | Unity to Arc | Name cartridge bytes, challenge, difficulty mode, cycle, party, and controlled agent. |
| `opened` | Arc to Unity | Return the exact action spec, initial snapshot, and spec digest. |
| `input` | Unity to Arc | Submit one or more ordered quantized input runs. |
| `snapshot` | Arc to Unity | Return authoritative tick, actor state, objective state, and presentation events. |
| `terminal` | Arc to Unity | Return the verified terminal state and complete action receipt. |
| `resume` | Unity to Arc | Resume only from the exact session id, spec digest, and acknowledged tick. |
| `abort` | Either direction | End presentation without fabricating an encounter result. |
| `refused` | Arc to Unity | Return a stable refusal code and no state mutation. |

Input uses the Arc vocabulary exactly:

```text
moveX, moveY     -1 | 0 | 1
aimX, aimY       -1 | 0 | 1
buttons           light | heavy | dodge | parry bitmask
```

Unity may batch repeated input for transport efficiency. Arc expands every run into fixed ticks and refuses gaps, overlaps, reordered sequences, input after a terminal state, unknown buttons, or a batch beyond the negotiated limit. Presentation interpolation never enters the action receipt.

## Unity package boundary

The package lives under:

```text
unity/Packages/com.bigbirdreturns.axm-action-player/
```

Its runtime surface is divided into five parts:

1. `ActionBridgeClient` manages TCP connection, message ordering, bounded queues, reconnect, and refusal state.
2. `ActionInputQuantizer` converts keyboard, gamepad, touch, controller, hand, or body observations into the five Arc input fields.
3. `ActionSessionDriver` advances the transport clock, submits bounded input runs, and exposes authoritative snapshots.
4. `ActionArenaPresenter` pools player, enemy, objective, telegraph, hit, and completion representations. It never runs collision or damage law.
5. `ActionPlacementRoot` binds the arena to the existing plane and anchor system through a small interface rather than importing a second AR stack.

The package includes no physics engine, pathfinder, inference runtime, cloud SDK, marketplace client, or remote asset dependency.

## AR placement and scale

Action simulation coordinates are integer law. Unity coordinates are presentation.

The arena root supports two modes:

- `life-size`, where a configured number of simulation units maps to one physical meter;
- `tabletop`, where the action arena is uniformly fitted inside the accepted plane footprint.

Uniform scale, rotation, and root translation may change how the encounter is seen. They do not change range tests, movement, timing, damage, or receipt identity. Non-uniform scale is refused because it would visually misrepresent distance law.

The existing tap-to-place and anchor-continuity systems own placement. The action package receives an accepted pose, plane extent, anchor id, and tracking quality through `IActionPlacementProvider`.

## Tracked input modes

The first package supports four presentation mappings over the same Arc input:

- `screen`: keyboard, gamepad, and touch controls;
- `controller-directed`: left stick or controller displacement for movement, right stick or controller ray for aim, buttons for actions;
- `hand-directed`: palm or wrist direction for movement and aim, with explicitly calibrated gestures for light, heavy, dodge, and parry;
- `room-relative`: bounded body displacement supplies direction while actions remain on controller or gesture inputs.

Gesture recognition remains presentation policy. A gesture is recorded as physical evidence before it becomes a quantized action input. The action receipt records the quantized input that Arc adjudicated. The embodied capsule records the observation and mapping that produced it.

## Physical safety and evidence

A game avatar cannot injure the player, but an AR presentation can induce unsafe movement. The package therefore exposes a physical presentation envelope containing:

- accepted play volume;
- guardian or room-boundary margin;
- minimum tracking quality;
- allowed locomotion mapping;
- maximum presentation scale;
- maximum camera impulse and rotational acceleration;
- pause-on-tracking-loss behavior.

The Unity player pauses input submission when placement or tracking leaves the accepted envelope. It sends no synthetic neutral ticks unless Arc has explicitly negotiated them. A local pause is presentation state, not an action outcome.

`axm-unity-action-frame/1` records the minimal evidence needed to explain physical interaction:

```text
monotonic frame and action tick
camera pose and tracking state
placement anchor id and root transform
accepted play-volume digest
raw input observation class
quantized ActionInput
Arc snapshot digest acknowledged by Unity
presentation quality tier
```

This stream may enter Flash Freeze as a hot, gap-checked source. An incident shard cites both the physical-envelope shard and the action receipt when available. The two artifacts answer different questions: the action receipt proves what the deterministic game accepted; the embodied shard proves what the device observed and presented.

## Low-power presentation law

The constrained profile targets the same finite runtime law already accepted by Arc:

- 30 action ticks per second;
- at most twelve active enemies;
- two authoritative snapshots may be interpolated without simulation work in Unity;
- pooled GameObjects or Entities with no per-frame instantiate/destroy loop;
- one primary unshadowed light in AR;
- no mandatory post-processing;
- no dynamic rigid-body debris;
- material and mesh reuse by enemy kit;
- update work limited to visible and active actors;
- quality changes may alter particles, trails, animation sampling, shadows, and resolution, but never action law.

The initial Quest and older-phone target is a stable 30 rendered frames per second. Desktop may render faster while still consuming the same 30 Hz authority.

## Scene compiler extension

The existing scene compiler receives one new presentation-only job object:

```json
{
  "format": "axm-unity-action-scene-job/1",
  "actionSpecPath": "input/encounter.action-spec.json",
  "presentation": {
    "mode": "tabletop",
    "targetDiameterMeters": 0.9,
    "playerPrefab": "primitive-player-v1",
    "enemyPrefabs": {
      "skirmisher": "primitive-skirmisher-v1",
      "duelist": "primitive-duelist-v1",
      "swarm": "primitive-swarm-v1",
      "hexer": "primitive-hexer-v1",
      "breaker": "primitive-breaker-v1"
    }
  }
}
```

The compiler may create arena meshes, pooled presentation objects, labels, and receipt bindings. It may not calculate enemy population, completion thresholds, attack timing, or damage. Those values arrive from the action spec.

## Acceptance gates

The bridge is accepted only when all of the following are true:

1. Arc opens and completes the same encounter through the ordinary TypeScript action authority while Unity acts only as input and renderer.
2. A captured Unity input stream replayed without Unity produces the identical action receipt.
3. Delayed, duplicated, missing, reordered, oversized, and post-terminal input batches are refused without mutation.
4. Tabletop and life-size presentations produce the same receipt from the same quantized trace.
5. Plane loss, anchor loss, and tracking loss pause safely and do not create an action result.
6. The Unity package passes edit-mode protocol, quantization, interpolation, placement-scale, queue-bound, and evidence-frame tests.
7. The existing Embodied-AR-Lab camera, plane, tap-to-place, anchor-continuity, scene-compiler, edit-mode, and play-mode receipts remain green.
8. Windows standalone and Quest/Android builds load the same spec and preserve exact receipt export.
9. A Flash Freeze capsule can bind physical frame evidence to the exact action receipt and physical-envelope shard without making either artifact authoritative for the other.

## Current boundary

The sidecar topology is the first production path because it reuses one accepted action authority immediately. Desktop can host the sidecar on the same machine. Quest can use a LAN host such as the existing NUC or desktop during development. A self-contained Quest player requires a later accepted embedding path, either a conformance-proven C# mirror or the exact Arc kernel compiled into an offline native or WebAssembly module.

The governing control question is: can Unity provide convincing embodied action, tracked AR placement, and physical evidence while every combat and campaign fact remains reproducible from Arc law and the exact quantized trace alone?
