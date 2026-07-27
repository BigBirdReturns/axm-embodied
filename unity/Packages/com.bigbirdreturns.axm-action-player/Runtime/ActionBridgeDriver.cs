using System;
using System.Threading.Tasks;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public enum ActionBridgeSessionState
    {
        Disconnected,
        Connecting,
        Handshaking,
        Ready,
        Opening,
        Playing,
        Terminal,
        Refused,
        Faulted
    }

    public sealed class ActionBridgeDriver : MonoBehaviour
    {
        [Header("Bridge")]
        [SerializeField] private string host = "127.0.0.1";
        [SerializeField] private int port = ActionBridgeProtocol.DefaultPort;
        [SerializeField] private bool connectOnStart = true;
        [SerializeField] private int maximumMessagesPerFrame = 64;
        [SerializeField] private int maximumCatchUpTicksPerFrame = 4;

        [Header("Input")]
        [SerializeField] private MonoBehaviour inputSourceComponent;
        [SerializeField] private int preferredInputBatchTicks = 2;

        private ActionBridgeConnection connection;
        private IActionInputSource inputSource;
        private ActionInputRunBuilder inputRuns;
        private string sessionId;
        private long outgoingSequence;
        private int tickRate = ActionBridgeProtocol.TickRate;
        private int negotiatedMaximumBatch = ActionBridgeProtocol.DefaultMaximumInputBatchTicks;
        private int nextInputTick;
        private float tickAccumulator;
        private bool physicalPause;
        private bool sendInFlight;
        private string pendingArcJson = string.Empty;
        private string pendingChallengeId = string.Empty;
        private string pendingDifficultyModeId = string.Empty;
        private int pendingCycle;
        private string pendingControlledAgentId = string.Empty;
        private string[] pendingPartyAgentIds = Array.Empty<string>();

        public event Action<ActionHelloAcceptedMessage> HelloAccepted;
        public event Action<ActionOpenedMessage> SessionOpened;
        public event Action<ActionSnapshotMessage> SnapshotReceived;
        public event Action<ActionTerminalMessage> SessionCompleted;
        public event Action<ActionRefusedMessage> SessionRefused;
        public event Action<string> BridgeFaulted;
        public event Action<ActionInputFrame, int> InputSampled;

        public ActionBridgeSessionState SessionState { get; private set; } = ActionBridgeSessionState.Disconnected;
        public ActionSpecWire CurrentSpec { get; private set; }
        public ActionSnapshotMessage CurrentSnapshot { get; private set; }
        public ActionInputFrame LastInput { get; private set; } = new ActionInputFrame();
        public string SessionId => sessionId ?? string.Empty;
        public string LastError { get; private set; } = string.Empty;
        public bool IsPhysicallyPaused => physicalPause;
        public int TickRate => tickRate;

        private async void Start()
        {
            inputSource = inputSourceComponent as IActionInputSource;
            if (inputSourceComponent != null && inputSource == null)
            {
                Fault("The configured input source does not implement IActionInputSource.");
                return;
            }

            if (connectOnStart)
            {
                await ConnectAsync();
            }
        }

        private void Update()
        {
            DrainIncomingMessages();

            if (connection != null && connection.State == ActionBridgeConnectionState.Faulted)
            {
                Fault(connection.LastError);
            }

            if (SessionState != ActionBridgeSessionState.Playing || physicalPause || inputSource == null)
            {
                return;
            }

            tickAccumulator += Mathf.Max(0f, Time.unscaledDeltaTime);
            float tickDuration = 1f / Mathf.Max(1, tickRate);
            int sampled = 0;
            while (tickAccumulator >= tickDuration && sampled < Mathf.Max(1, maximumCatchUpTicksPerFrame))
            {
                tickAccumulator -= tickDuration;
                SampleOneTick();
                sampled += 1;
            }

            if (sampled >= maximumCatchUpTicksPerFrame && tickAccumulator > tickDuration * maximumCatchUpTicksPerFrame)
            {
                tickAccumulator = tickDuration * maximumCatchUpTicksPerFrame;
            }

            if (inputRuns != null && !inputRuns.IsEmpty
                && (inputRuns.IsFull || inputRuns.TickCount >= Mathf.Clamp(preferredInputBatchTicks, 1, negotiatedMaximumBatch)))
            {
                _ = FlushInputAsync();
            }
        }

        private async void OnDestroy()
        {
            if (connection != null)
            {
                await connection.DisconnectAsync();
                connection.Dispose();
                connection = null;
            }
        }

        public void SetInputSource(MonoBehaviour source)
        {
            IActionInputSource candidate = source as IActionInputSource;
            if (source != null && candidate == null)
            {
                throw new ArgumentException("Input source must implement IActionInputSource.", nameof(source));
            }

            inputSourceComponent = source;
            inputSource = candidate;
        }

        public void SetPhysicalPause(bool paused)
        {
            physicalPause = paused;
            if (paused)
            {
                tickAccumulator = 0f;
                if (inputRuns != null && !inputRuns.IsEmpty)
                {
                    _ = FlushInputAsync();
                }
            }
        }

        public async Task ConnectAsync()
        {
            if (SessionState != ActionBridgeSessionState.Disconnected && SessionState != ActionBridgeSessionState.Faulted)
            {
                return;
            }

            LastError = string.Empty;
            SessionState = ActionBridgeSessionState.Connecting;
            connection?.Dispose();
            connection = new ActionBridgeConnection();
            sessionId = Guid.NewGuid().ToString("N");
            outgoingSequence = 0;

            try
            {
                await connection.ConnectAsync(host, Mathf.Clamp(port, 1, 65535));
                SessionState = ActionBridgeSessionState.Handshaking;
                ActionHelloMessage hello = new ActionHelloMessage
                {
                    sessionId = sessionId,
                    sequence = NextSequence(),
                    requestedMaximumInputBatchTicks = Mathf.Clamp(preferredInputBatchTicks * 4, 1, 120)
                };
                await connection.SendJsonAsync(ActionProtocolJson.Serialize(hello));
            }
            catch (Exception exception)
            {
                Fault(exception.Message);
            }
        }

        public async Task OpenSessionAsync(
            string arcJson,
            string challengeId,
            string difficultyModeId,
            int cycle,
            string controlledAgentId,
            string[] partyAgentIds)
        {
            if (SessionState != ActionBridgeSessionState.Ready)
            {
                throw new InvalidOperationException("The bridge must complete its handshake before opening a session.");
            }

            if (string.IsNullOrWhiteSpace(arcJson)) throw new ArgumentException("Arc JSON is empty.", nameof(arcJson));
            if (string.IsNullOrWhiteSpace(challengeId)) throw new ArgumentException("Challenge id is empty.", nameof(challengeId));
            if (string.IsNullOrWhiteSpace(controlledAgentId)) throw new ArgumentException("Controlled agent id is empty.", nameof(controlledAgentId));
            if (partyAgentIds == null || partyAgentIds.Length == 0) throw new ArgumentException("Party is empty.", nameof(partyAgentIds));

            pendingArcJson = arcJson;
            pendingChallengeId = challengeId;
            pendingDifficultyModeId = difficultyModeId ?? string.Empty;
            pendingCycle = Math.Max(0, cycle);
            pendingControlledAgentId = controlledAgentId;
            pendingPartyAgentIds = (string[])partyAgentIds.Clone();

            ActionOpenMessage open = new ActionOpenMessage
            {
                sessionId = sessionId,
                sequence = NextSequence(),
                arcJson = pendingArcJson,
                challengeId = pendingChallengeId,
                difficultyModeId = pendingDifficultyModeId,
                cycle = pendingCycle,
                controlledAgentId = pendingControlledAgentId,
                partyAgentIds = pendingPartyAgentIds
            };

            SessionState = ActionBridgeSessionState.Opening;
            await connection.SendJsonAsync(ActionProtocolJson.Serialize(open));
        }

        public async Task AbortSessionAsync(string reason)
        {
            if (connection == null || !connection.IsConnected)
            {
                return;
            }

            ActionAbortMessage abort = new ActionAbortMessage
            {
                sessionId = sessionId,
                sequence = NextSequence(),
                reason = string.IsNullOrWhiteSpace(reason) ? "unity-presentation-abort" : reason
            };
            await connection.SendJsonAsync(ActionProtocolJson.Serialize(abort));
            inputRuns?.Clear();
            CurrentSpec = null;
            CurrentSnapshot = null;
            SessionState = ActionBridgeSessionState.Ready;
        }

        private void SampleOneTick()
        {
            ActionInputFrame sample = ActionInputQuantizer.Normalize(inputSource.SampleActionInput());
            LastInput = sample;
            if (inputRuns == null)
            {
                inputRuns = new ActionInputRunBuilder(negotiatedMaximumBatch);
            }

            if (!inputRuns.TryAppend(sample))
            {
                _ = FlushInputAsync();
                if (!inputRuns.TryAppend(sample))
                {
                    Fault("The input run builder refused a tick after flushing.");
                    return;
                }
            }

            InputSampled?.Invoke(sample, nextInputTick + inputRuns.TickCount - 1);
        }

        private async Task FlushInputAsync()
        {
            if (sendInFlight || inputRuns == null || inputRuns.IsEmpty || connection == null || !connection.IsConnected)
            {
                return;
            }

            sendInFlight = true;
            ActionInputRun[] runs = inputRuns.Drain();
            int ticks = 0;
            for (int index = 0; index < runs.Length; index += 1)
            {
                ticks += Math.Max(0, runs[index].ticks);
            }

            ActionInputMessage message = new ActionInputMessage
            {
                sessionId = sessionId,
                sequence = NextSequence(),
                firstTick = nextInputTick,
                runs = runs
            };
            nextInputTick += ticks;

            try
            {
                await connection.SendJsonAsync(ActionProtocolJson.Serialize(message));
            }
            catch (Exception exception)
            {
                Fault(exception.Message);
            }
            finally
            {
                sendInFlight = false;
            }
        }

        private void DrainIncomingMessages()
        {
            if (connection == null)
            {
                return;
            }

            int limit = Mathf.Clamp(maximumMessagesPerFrame, 1, 1024);
            for (int index = 0; index < limit && connection.TryDequeue(out string json); index += 1)
            {
                try
                {
                    Dispatch(json);
                }
                catch (Exception exception)
                {
                    Fault(exception.Message);
                    return;
                }
            }
        }

        private void Dispatch(string json)
        {
            string kind = ActionProtocolJson.Kind(json);
            switch (kind)
            {
                case "hello-accepted":
                {
                    ActionHelloAcceptedMessage accepted = ActionProtocolJson.Parse<ActionHelloAcceptedMessage>(json);
                    RequireSession(accepted.sessionId);
                    tickRate = accepted.tickRate <= 0 ? ActionBridgeProtocol.TickRate : accepted.tickRate;
                    negotiatedMaximumBatch = Mathf.Clamp(accepted.maximumInputBatchTicks, 1, 120);
                    inputRuns = new ActionInputRunBuilder(negotiatedMaximumBatch);
                    SessionState = ActionBridgeSessionState.Ready;
                    HelloAccepted?.Invoke(accepted);
                    break;
                }
                case "opened":
                {
                    ActionOpenedMessage opened = ActionProtocolJson.Parse<ActionOpenedMessage>(json);
                    RequireSession(opened.sessionId);
                    if (opened.spec == null || string.IsNullOrWhiteSpace(opened.spec.specDigest))
                    {
                        throw new FormatException("Opened message lacks an exact action spec digest.");
                    }
                    CurrentSpec = opened.spec;
                    CurrentSnapshot = opened.snapshot;
                    nextInputTick = opened.snapshot == null ? 0 : opened.snapshot.tick;
                    tickAccumulator = 0f;
                    inputRuns.Clear();
                    SessionState = ActionBridgeSessionState.Playing;
                    SessionOpened?.Invoke(opened);
                    if (opened.snapshot != null)
                    {
                        SnapshotReceived?.Invoke(opened.snapshot);
                    }
                    break;
                }
                case "snapshot":
                {
                    ActionSnapshotMessage snapshot = ActionProtocolJson.Parse<ActionSnapshotMessage>(json);
                    RequireSession(snapshot.sessionId);
                    CurrentSnapshot = snapshot;
                    SnapshotReceived?.Invoke(snapshot);
                    break;
                }
                case "terminal":
                {
                    ActionTerminalMessage terminal = ActionProtocolJson.Parse<ActionTerminalMessage>(json);
                    RequireSession(terminal.sessionId);
                    CurrentSnapshot = terminal.snapshot;
                    inputRuns?.Clear();
                    SessionState = ActionBridgeSessionState.Terminal;
                    SessionCompleted?.Invoke(terminal);
                    break;
                }
                case "refused":
                {
                    ActionRefusedMessage refused = ActionProtocolJson.Parse<ActionRefusedMessage>(json);
                    RequireSession(refused.sessionId);
                    LastError = string.IsNullOrWhiteSpace(refused.code)
                        ? refused.message
                        : refused.code + ": " + refused.message;
                    inputRuns?.Clear();
                    SessionState = ActionBridgeSessionState.Refused;
                    SessionRefused?.Invoke(refused);
                    break;
                }
                default:
                    throw new FormatException("Unknown action bridge message kind: " + kind);
            }
        }

        private void RequireSession(string incomingSessionId)
        {
            if (!string.Equals(sessionId, incomingSessionId, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("Bridge response session id does not match the active holder session.");
            }
        }

        private long NextSequence()
        {
            outgoingSequence += 1;
            return outgoingSequence;
        }

        private void Fault(string message)
        {
            LastError = string.IsNullOrWhiteSpace(message) ? "Unknown action bridge fault." : message;
            SessionState = ActionBridgeSessionState.Faulted;
            BridgeFaulted?.Invoke(LastError);
        }
    }
}
