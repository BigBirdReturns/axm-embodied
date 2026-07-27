# Primitive Action Arena sample

This sample is the smallest desktop smoke for the bridge before AR placement is attached.

Create an empty scene with these objects:

```text
Action Runtime
  ActionSidecarLauncher
  ActionBridgeDriver
  LegacyKeyboardActionInputSource

Action Placement
  FixedActionPlacementProvider
  ActionPlacementRoot
  ActionPhysicalEnvelopeController

Action Presentation
  ActionArenaPresenter
  ActionEvidenceRecorder
```

Set the bridge driver's input source to `LegacyKeyboardActionInputSource`. Set the placement root's provider to `FixedActionPlacementProvider`. Set the presenter and physical-envelope controller references. Use the included `primitive-action-scene-job.json` in `ActionSceneCompilerAdapter`.

The default desktop controls are:

```text
WASD / arrows   movement and aim
J               light attack
K               heavy attack
Space           dodge
L               parry
```

The sample does not include authored meshes. `ActionArenaPresenter` creates collider-free primitive bodies when no prefabs are supplied. This proves transport, input, interpolation, pooling, terminal receipt, and evidence output before cartridge art is introduced.
