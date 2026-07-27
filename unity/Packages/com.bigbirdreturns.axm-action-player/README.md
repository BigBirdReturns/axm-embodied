# AXM Action Player for Unity

This package turns Unity into a renderer and tracked-input client for the Arc-owned deterministic action runtime. Unity does not calculate combat results. It sends quantized input to the Arc authority sidecar, receives exact snapshots, and exports the returned `axm-action-receipt/1` alongside optional physical evidence.

## Install into Embodied-AR-Lab

For a local checkout, add this line to the Unity project's `Packages/manifest.json` dependencies object:

```json
"com.bigbirdreturns.axm-action-player": "file:../../axm-embodied/unity/Packages/com.bigbirdreturns.axm-action-player"
```

A Git dependency may be used after the branch is accepted:

```json
"com.bigbirdreturns.axm-action-player": "https://github.com/BigBirdReturns/axm-embodied.git?path=unity/Packages/com.bigbirdreturns.axm-action-player#feature/unity-action-player-v1"
```

The first integration target is Unity 6000.0.66f2.

## Minimal scene

Create one root object and add:

1. `ActionBridgeDriver`.
2. An `IActionInputSource`, such as `LegacyKeyboardActionInputSource` for desktop smoke.
3. `ActionPlacementRoot`.
4. The existing Embodied-AR-Lab plane, tap-to-place, and anchor component through an adapter implementing `IActionPlacementProvider`.
5. `ActionArenaPresenter`.
6. `ActionPhysicalEnvelopeController`.
7. `ActionEvidenceRecorder` when physical provenance is required.

The package includes `FixedActionPlacementProvider` for a no-AR smoke scene. It is a test fallback, not a replacement for the project's accepted placement stack.

## Start the Arc authority

From the exact action-authority checkout:

```bash
npx vite-node src/action-bridge/cli.ts --host 127.0.0.1 --port 47631
```

`ActionSidecarLauncher` can start this process automatically in the Unity Editor and desktop standalone. Android and Quest use a configured LAN host during the first integration phase.

## Open a session

Call:

```csharp
await bridge.OpenSessionAsync(
    arcJson,
    challengeId,
    difficultyModeId,
    cycle,
    organizationSeed,
    controlledAgentId,
    partyAgentIds);
```

The driver sends input only after the exact spec is accepted. It stops submitting ticks when the physical envelope pauses the presentation. The sidecar returns the terminal receipt after Arc completes the deterministic simulation.

## AR adapter seam

Embodied-AR-Lab should implement:

```csharp
public interface IActionPlacementProvider
{
    bool TryGetActionPlacement(out ActionPlacementPose placement);
}
```

The provider should reuse the project's current plane exposure, tap-to-place, tracking-quality, and anchor-continuity receipts. `ActionPlacementRoot` accepts only one uniform presentation mapping. Tabletop and life-size scale never enter combat law.

## Evidence seam

`ActionEvidenceRecorder` writes `axm-unity-action-frame/1` JSONL under `Application.persistentDataPath`. Each line binds camera pose, action tick, placement anchor, physical-envelope digest, quantized input, and the latest Arc snapshot digest. The stream is shaped for ingestion by the existing Flash Freeze and Genesis Shard pipeline.

## Current limits

The package deliberately contains no local C# combat mirror. The first accepted topology keeps one authority by running the Arc kernel in the sidecar. Self-contained Quest operation remains a later embedding train that must pass the same receipt vectors before it may replace the sidecar.
