using System;
using NUnit.Framework;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer.Tests
{
    public sealed class ActionPlayerContractTests
    {
        [Test]
        public void HelloRoundTripsThroughUnityJson()
        {
            ActionHelloMessage hello = new ActionHelloMessage
            {
                sessionId = "holder-session",
                sequence = 1,
                requestedMaximumInputBatchTicks = 8
            };

            string json = ActionProtocolJson.Serialize(hello);
            Assert.That(ActionProtocolJson.Kind(json), Is.EqualTo("hello"));
            ActionHelloMessage restored = ActionProtocolJson.Parse<ActionHelloMessage>(json);
            Assert.That(restored.format, Is.EqualTo(ActionBridgeProtocol.Format));
            Assert.That(restored.sessionId, Is.EqualTo("holder-session"));
            Assert.That(restored.requestedTickRate, Is.EqualTo(30));
            Assert.That(restored.requestedMaximumInputBatchTicks, Is.EqualTo(8));
        }

        [Test]
        public void OpenMessageCarriesOrganizationSeedAndExactParty()
        {
            ActionOpenMessage open = new ActionOpenMessage
            {
                sessionId = "session",
                sequence = 2,
                arcJson = "{\"id\":\"fixture\"}",
                challengeId = "challenge",
                cycle = 7,
                organizationSeed = 12345,
                controlledAgentId = "agent-a",
                partyAgentIds = new[] { "agent-a", "agent-b" }
            };

            ActionOpenMessage restored = ActionProtocolJson.Parse<ActionOpenMessage>(ActionProtocolJson.Serialize(open));
            Assert.That(restored.organizationSeed, Is.EqualTo(12345));
            Assert.That(restored.partyAgentIds, Is.EqualTo(new[] { "agent-a", "agent-b" }));
        }

        [TestCase(-0.34f, 0)]
        [TestCase(0.34f, 0)]
        [TestCase(-0.36f, -1)]
        [TestCase(0.36f, 1)]
        [TestCase(float.NaN, 0)]
        [TestCase(float.PositiveInfinity, 0)]
        public void QuantizerUsesBoundedThreeStateAxes(float value, int expected)
        {
            Assert.That(ActionInputQuantizer.Axis(value, 0.35f), Is.EqualTo(expected));
        }

        [Test]
        public void RunBuilderCompressesOnlyIdenticalConsecutiveTicks()
        {
            ActionInputRunBuilder builder = new ActionInputRunBuilder(6);
            ActionInputFrame idle = new ActionInputFrame();
            ActionInputFrame light = new ActionInputFrame { buttons = ActionBridgeProtocol.LightButton };

            Assert.That(builder.TryAppend(idle), Is.True);
            Assert.That(builder.TryAppend(idle), Is.True);
            Assert.That(builder.TryAppend(light), Is.True);
            Assert.That(builder.TryAppend(light), Is.True);
            Assert.That(builder.TryAppend(idle), Is.True);

            ActionInputRun[] runs = builder.Drain();
            Assert.That(runs, Has.Length.EqualTo(3));
            Assert.That(runs[0].ticks, Is.EqualTo(2));
            Assert.That(runs[1].ticks, Is.EqualTo(2));
            Assert.That(runs[2].ticks, Is.EqualTo(1));
            Assert.That(builder.IsEmpty, Is.True);
        }

        [Test]
        public void SceneJobRefusesNonUniformOrUnknownPresentationLaw()
        {
            ActionSceneJob accepted = new ActionSceneJob
            {
                presentation = new ActionScenePresentation
                {
                    mode = "tabletop",
                    targetDiameterMeters = 0.9f,
                    simulationUnitsPerMeter = 1000f,
                    playerPrefab = "primitive-player-v1"
                }
            };
            Assert.DoesNotThrow(() => ActionSceneCompilerAdapter.Validate(accepted));

            ActionSceneJob badMode = JsonUtility.FromJson<ActionSceneJob>(JsonUtility.ToJson(accepted));
            badMode.presentation.mode = "stretch-to-plane";
            Assert.Throws<FormatException>(() => ActionSceneCompilerAdapter.Validate(badMode));

            ActionSceneJob badScale = JsonUtility.FromJson<ActionSceneJob>(JsonUtility.ToJson(accepted));
            badScale.presentation.simulationUnitsPerMeter = 0f;
            Assert.Throws<FormatException>(() => ActionSceneCompilerAdapter.Validate(badScale));
        }

        [Test]
        public void TabletopPlacementChangesOnlyPresentationMapping()
        {
            GameObject rootObject = new GameObject("action-root");
            GameObject providerObject = new GameObject("placement-provider");
            try
            {
                FixedActionPlacementProvider provider = providerObject.AddComponent<FixedActionPlacementProvider>();
                ActionPlacementRoot root = rootObject.AddComponent<ActionPlacementRoot>();
                root.SetPlacementProvider(provider);
                root.Configure(ActionPresentationScaleMode.Tabletop, 0.9f, 1000f);
                root.BindSpec(new ActionSpecWire
                {
                    specDigest = "actspec1_fixture",
                    arena = new ActionArenaWire { kit = "ring", radius = 6000 }
                });

                Vector3 edge = root.MapSimulationPosition(6000, 0);
                Assert.That(edge.x, Is.GreaterThan(0f));
                Assert.That(edge.x, Is.LessThanOrEqualTo(0.45f).Within(0.001f));
                Assert.That(root.ArenaRoot.localScale, Is.EqualTo(Vector3.one));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(providerObject);
                UnityEngine.Object.DestroyImmediate(rootObject);
            }
        }
    }
}
