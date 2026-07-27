using System;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public static class ActionBridgeProtocol
    {
        public const string Format = "axm-action-bridge/1";
        public const string UnityFrameFormat = "axm-unity-action-frame/1";
        public const string SceneJobFormat = "axm-unity-action-scene-job/1";
        public const int TickRate = 30;
        public const int DefaultPort = 47631;
        public const int DefaultMaximumInputBatchTicks = 12;
        public const int DefaultMaximumQueuedMessages = 256;
        public const int DefaultMaximumLineBytes = 4 * 1024 * 1024;

        public const int LightButton = 1;
        public const int HeavyButton = 2;
        public const int DodgeButton = 4;
        public const int ParryButton = 8;
        public const int ButtonMask = 15;
    }

    [Serializable]
    public sealed class ActionMessageHeader
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = string.Empty;
    }

    [Serializable]
    public sealed class ActionInputFrame
    {
        public int moveX;
        public int moveY;
        public int aimX;
        public int aimY;
        public int buttons;

        public ActionInputFrame Clone()
        {
            return new ActionInputFrame
            {
                moveX = moveX,
                moveY = moveY,
                aimX = aimX,
                aimY = aimY,
                buttons = buttons
            };
        }

        public bool SameAs(ActionInputFrame other)
        {
            return other != null
                && moveX == other.moveX
                && moveY == other.moveY
                && aimX == other.aimX
                && aimY == other.aimY
                && buttons == other.buttons;
        }
    }

    [Serializable]
    public sealed class ActionInputRun
    {
        public int ticks;
        public ActionInputFrame input = new ActionInputFrame();
    }

    [Serializable]
    public sealed class ActionHelloMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "hello";
        public string client = "unity";
        public string clientVersion = "0.1.0";
        public string requestedRuntimeVersion = "1.0.0";
        public int requestedTickRate = ActionBridgeProtocol.TickRate;
        public int requestedMaximumInputBatchTicks = ActionBridgeProtocol.DefaultMaximumInputBatchTicks;
    }

    [Serializable]
    public sealed class ActionHelloAcceptedMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "hello-accepted";
        public string runtimeVersion = string.Empty;
        public int tickRate;
        public int maximumInputBatchTicks;
        public string authorityCommit = string.Empty;
    }

    [Serializable]
    public sealed class ActionOpenMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "open";
        public string arcJson = string.Empty;
        public string challengeId = string.Empty;
        public string difficultyModeId = string.Empty;
        public int cycle;
        public string controlledAgentId = string.Empty;
        public string[] partyAgentIds = Array.Empty<string>();
    }

    [Serializable]
    public sealed class ActionInputMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "input";
        public int firstTick;
        public ActionInputRun[] runs = Array.Empty<ActionInputRun>();
    }

    [Serializable]
    public sealed class ActionResumeMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "resume";
        public string actionSpecDigest = string.Empty;
        public int acknowledgedTick;
    }

    [Serializable]
    public sealed class ActionAbortMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "abort";
        public string reason = string.Empty;
    }

    [Serializable]
    public sealed class ActionArenaWire
    {
        public string kit = string.Empty;
        public int radius;
    }

    [Serializable]
    public sealed class ActionAttackLawWire
    {
        public string id = string.Empty;
        public int startupTicks;
        public int activeTicks;
        public int recoveryTicks;
        public int damage;
        public int range;
        public int coneNumerator;
        public int coneDenominator;
        public int knockback;
    }

    [Serializable]
    public sealed class ActionPlayerLawWire
    {
        public string kit = string.Empty;
        public int maxHealth;
        public int radius;
        public int movePerTick;
        public int dodgePerTick;
        public int dodgeTicks;
        public int dodgeInvulnerableTicks;
        public int parryTicks;
        public int parryActiveTicks;
        public int parryRecoveryTicks;
        public int staggerTicks;
        public ActionAttackLawWire[] attacks = Array.Empty<ActionAttackLawWire>();
    }

    [Serializable]
    public sealed class ActionEnemyLawWire
    {
        public string kit = string.Empty;
        public int maxHealth;
        public int radius;
        public int movePerTick;
        public int attackRange;
        public int attackDamage;
        public int telegraphTicks;
        public int activeTicks;
        public int recoveryTicks;
        public int staggerTicks;
    }

    [Serializable]
    public sealed class ActionObjectiveWire
    {
        public string id = string.Empty;
        public string label = string.Empty;
        public string brief = string.Empty;
        public string enemyKit = string.Empty;
        public int enemyCount;
        public int targetDefeats;
        public string failureKind = string.Empty;
        public float severity;
    }

    [Serializable]
    public sealed class ActionCompletionWire
    {
        public string kind = string.Empty;
        public int successObjectiveCount;
        public int partialObjectiveCount;
    }

    [Serializable]
    public sealed class ActionSpecWire
    {
        public string format = string.Empty;
        public string runtimeVersion = string.Empty;
        public string arcDigest = string.Empty;
        public string challengeId = string.Empty;
        public string title = string.Empty;
        public string difficultyModeId = string.Empty;
        public int tickRate;
        public int maxTicks;
        public ActionArenaWire arena = new ActionArenaWire();
        public ActionPlayerLawWire player = new ActionPlayerLawWire();
        public ActionEnemyLawWire[] enemyLaws = Array.Empty<ActionEnemyLawWire>();
        public ActionObjectiveWire[] objectives = Array.Empty<ActionObjectiveWire>();
        public ActionCompletionWire completion = new ActionCompletionWire();
        public string specDigest = string.Empty;
    }

    [Serializable]
    public sealed class ActionPlayerSnapshot
    {
        public int x;
        public int y;
        public int facingX;
        public int facingY;
        public int health;
        public string mode = string.Empty;
        public int modeTick;
    }

    [Serializable]
    public sealed class ActionEnemySnapshot
    {
        public string id = string.Empty;
        public string objectiveId = string.Empty;
        public string kit = string.Empty;
        public int x;
        public int y;
        public int health;
        public string mode = string.Empty;
        public int modeTick;
    }

    [Serializable]
    public sealed class ActionObjectiveSnapshot
    {
        public string id = string.Empty;
        public int defeated;
        public int target;
        public bool completed;
    }

    [Serializable]
    public sealed class ActionStatsWire
    {
        public int hitsLanded;
        public int heavyHits;
        public int damageTaken;
        public int parries;
        public int dodgedAttacks;
        public int enemiesDefeated;
    }

    [Serializable]
    public sealed class ActionPresentationEventWire
    {
        public string type = string.Empty;
        public string actorId = string.Empty;
        public string enemyId = string.Empty;
        public string objectiveId = string.Empty;
        public string action = string.Empty;
        public string outcome = string.Empty;
        public int damage;
        public int health;
        public bool defeated;
    }

    [Serializable]
    public sealed class ActionOpenedMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "opened";
        public ActionSpecWire spec = new ActionSpecWire();
        public ActionSnapshotMessage snapshot = new ActionSnapshotMessage();
    }

    [Serializable]
    public sealed class ActionSnapshotMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "snapshot";
        public string actionSpecDigest = string.Empty;
        public int acknowledgedInputSequence;
        public int tick;
        public int activeObjectiveIndex;
        public ActionPlayerSnapshot player = new ActionPlayerSnapshot();
        public ActionEnemySnapshot[] enemies = Array.Empty<ActionEnemySnapshot>();
        public ActionObjectiveSnapshot[] objectives = Array.Empty<ActionObjectiveSnapshot>();
        public string[] completedObjectiveIds = Array.Empty<string>();
        public ActionStatsWire stats = new ActionStatsWire();
        public ActionPresentationEventWire[] events = Array.Empty<ActionPresentationEventWire>();
        public string snapshotDigest = string.Empty;
        public bool terminal;
        public string outcome = string.Empty;
    }

    [Serializable]
    public sealed class ActionTerminalMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "terminal";
        public ActionSnapshotMessage snapshot = new ActionSnapshotMessage();
        public string receiptFormat = string.Empty;
        public string receiptDigest = string.Empty;
        public string receiptJson = string.Empty;
    }

    [Serializable]
    public sealed class ActionRefusedMessage
    {
        public string format = ActionBridgeProtocol.Format;
        public string sessionId = string.Empty;
        public long sequence;
        public string kind = "refused";
        public string code = string.Empty;
        public string message = string.Empty;
        public int authoritativeTick;
        public string actionSpecDigest = string.Empty;
    }

    [Serializable]
    public sealed class ActionSceneJob
    {
        public string format = ActionBridgeProtocol.SceneJobFormat;
        public string actionSpecPath = string.Empty;
        public ActionScenePresentation presentation = new ActionScenePresentation();
    }

    [Serializable]
    public sealed class ActionScenePresentation
    {
        public string mode = "tabletop";
        public float targetDiameterMeters = 0.9f;
        public float simulationUnitsPerMeter = 1000f;
        public string playerPrefab = "primitive-player-v1";
        public ActionEnemyPrefabReference[] enemyPrefabs = Array.Empty<ActionEnemyPrefabReference>();
    }

    [Serializable]
    public sealed class ActionEnemyPrefabReference
    {
        public string kit = string.Empty;
        public string prefab = string.Empty;
    }

    public static class ActionProtocolJson
    {
        public static string Kind(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return string.Empty;
            }

            ActionMessageHeader header = JsonUtility.FromJson<ActionMessageHeader>(json);
            return header == null ? string.Empty : header.kind ?? string.Empty;
        }

        public static T Parse<T>(string json) where T : class
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("Bridge JSON is empty.", nameof(json));
            }

            T value = JsonUtility.FromJson<T>(json);
            if (value == null)
            {
                throw new FormatException("Bridge JSON did not produce a value of the requested type.");
            }

            return value;
        }

        public static string Serialize(object value)
        {
            if (value == null)
            {
                throw new ArgumentNullException(nameof(value));
            }

            return JsonUtility.ToJson(value, false);
        }
    }
}
