using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    [Serializable]
    public sealed class ActionUnityFrameRecord
    {
        public string format = ActionBridgeProtocol.UnityFrameFormat;
        public string sessionId = string.Empty;
        public long monotonicTimestamp;
        public int unityFrame;
        public int actionTick;
        public string actionSpecDigest = string.Empty;
        public string snapshotDigest = string.Empty;
        public string anchorId = string.Empty;
        public bool placementValid;
        public string trackingState = string.Empty;
        public string physicalEnvelopeDigest = string.Empty;
        public string rawObservationClass = string.Empty;
        public string qualityTier = string.Empty;
        public ActionInputFrame quantizedInput = new ActionInputFrame();
        public SerializablePose cameraPose = new SerializablePose();
        public SerializablePose arenaPose = new SerializablePose();
        public SerializableVector3 arenaScale = new SerializableVector3();
    }

    [Serializable]
    public sealed class SerializableVector3
    {
        public float x;
        public float y;
        public float z;

        public static SerializableVector3 From(Vector3 value)
        {
            return new SerializableVector3 { x = value.x, y = value.y, z = value.z };
        }
    }

    [Serializable]
    public sealed class SerializableQuaternion
    {
        public float x;
        public float y;
        public float z;
        public float w = 1f;

        public static SerializableQuaternion From(Quaternion value)
        {
            return new SerializableQuaternion { x = value.x, y = value.y, z = value.z, w = value.w };
        }
    }

    [Serializable]
    public sealed class SerializablePose
    {
        public SerializableVector3 position = new SerializableVector3();
        public SerializableQuaternion rotation = new SerializableQuaternion();

        public static SerializablePose From(Transform value)
        {
            if (value == null)
            {
                return new SerializablePose();
            }

            return new SerializablePose
            {
                position = SerializableVector3.From(value.position),
                rotation = SerializableQuaternion.From(value.rotation)
            };
        }
    }

    public sealed class ActionEvidenceRecorder : MonoBehaviour
    {
        [SerializeField] private ActionBridgeDriver driver;
        [SerializeField] private ActionPlacementRoot placementRoot;
        [SerializeField] private Camera evidenceCamera;
        [SerializeField] private string physicalEnvelopeDigest = string.Empty;
        [SerializeField] private string qualityTier = "constrained";
        [SerializeField, Min(1)] private int durableFlushIntervalRecords = 30;
        [SerializeField] private bool recordOnStart = true;

        private FileStream stream;
        private StreamWriter writer;
        private int recordsSinceFlush;
        private string outputPath = string.Empty;
        private string latestSnapshotDigest = string.Empty;
        private string latestActionSpecDigest = string.Empty;
        private string trackingState = "unknown";
        private string rawObservationClass = "unknown";

        public event Action<string> EvidenceLineWritten;

        public string OutputPath => outputPath;
        public bool IsRecording => writer != null;

        private void Awake()
        {
            if (evidenceCamera == null)
            {
                evidenceCamera = Camera.main;
            }
        }

        private void OnEnable()
        {
            if (driver != null)
            {
                driver.SessionOpened += OnSessionOpened;
                driver.SnapshotReceived += OnSnapshot;
                driver.SessionCompleted += OnTerminal;
                driver.InputSampled += OnInputSampled;
            }

            if (placementRoot != null)
            {
                placementRoot.PlacementValidityChanged += OnPlacementValidityChanged;
            }
        }

        private void OnDisable()
        {
            if (driver != null)
            {
                driver.SessionOpened -= OnSessionOpened;
                driver.SnapshotReceived -= OnSnapshot;
                driver.SessionCompleted -= OnTerminal;
                driver.InputSampled -= OnInputSampled;
            }

            if (placementRoot != null)
            {
                placementRoot.PlacementValidityChanged -= OnPlacementValidityChanged;
            }

            StopRecording(true);
        }

        public void SetPhysicalEnvelopeDigest(string digest)
        {
            physicalEnvelopeDigest = digest ?? string.Empty;
        }

        public void SetTrackingState(string state)
        {
            trackingState = string.IsNullOrWhiteSpace(state) ? "unknown" : state;
        }

        public void SetRawObservationClass(string observationClass)
        {
            rawObservationClass = string.IsNullOrWhiteSpace(observationClass) ? "unknown" : observationClass;
        }

        public void StartRecording(string sessionId)
        {
            StopRecording(true);
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                throw new ArgumentException("Evidence session id is empty.", nameof(sessionId));
            }

            string directory = Path.Combine(Application.persistentDataPath, "axm", "action", sessionId);
            Directory.CreateDirectory(directory);
            outputPath = Path.Combine(directory, "action-frames.jsonl");
            stream = new FileStream(
                outputPath,
                FileMode.Create,
                FileAccess.Write,
                FileShare.Read,
                64 * 1024,
                FileOptions.SequentialScan);
            writer = new StreamWriter(stream, new UTF8Encoding(false, true), 64 * 1024, true)
            {
                AutoFlush = false,
                NewLine = "\n"
            };
            recordsSinceFlush = 0;
        }

        public void StopRecording(bool durable)
        {
            if (writer == null)
            {
                return;
            }

            try
            {
                writer.Flush();
                if (durable)
                {
                    stream.Flush(true);
                }
            }
            finally
            {
                writer.Dispose();
                stream.Dispose();
                writer = null;
                stream = null;
                recordsSinceFlush = 0;
            }
        }

        private void OnSessionOpened(ActionOpenedMessage opened)
        {
            latestActionSpecDigest = opened?.spec?.specDigest ?? string.Empty;
            latestSnapshotDigest = opened?.snapshot?.snapshotDigest ?? string.Empty;
            if (recordOnStart && driver != null)
            {
                StartRecording(driver.SessionId);
            }
        }

        private void OnSnapshot(ActionSnapshotMessage snapshot)
        {
            latestSnapshotDigest = snapshot?.snapshotDigest ?? string.Empty;
        }

        private void OnTerminal(ActionTerminalMessage terminal)
        {
            latestSnapshotDigest = terminal?.snapshot?.snapshotDigest ?? latestSnapshotDigest;
            FlushDurably();
        }

        private void OnPlacementValidityChanged(bool valid)
        {
            trackingState = valid ? "tracked" : "placement-invalid";
        }

        private void OnInputSampled(ActionInputFrame input, int actionTick)
        {
            if (writer == null || driver == null)
            {
                return;
            }

            Transform arena = placementRoot == null ? null : placementRoot.ArenaRoot;
            ActionUnityFrameRecord record = new ActionUnityFrameRecord
            {
                sessionId = driver.SessionId,
                monotonicTimestamp = Stopwatch.GetTimestamp(),
                unityFrame = Time.frameCount,
                actionTick = actionTick,
                actionSpecDigest = latestActionSpecDigest,
                snapshotDigest = latestSnapshotDigest,
                anchorId = placementRoot == null ? string.Empty : placementRoot.AnchorId,
                placementValid = placementRoot == null || placementRoot.IsPlacementValid,
                trackingState = trackingState,
                physicalEnvelopeDigest = physicalEnvelopeDigest,
                rawObservationClass = rawObservationClass,
                qualityTier = qualityTier,
                quantizedInput = input?.Clone() ?? new ActionInputFrame(),
                cameraPose = SerializablePose.From(evidenceCamera == null ? null : evidenceCamera.transform),
                arenaPose = SerializablePose.From(arena),
                arenaScale = SerializableVector3.From(arena == null ? Vector3.one : arena.lossyScale)
            };

            string json = JsonUtility.ToJson(record, false);
            writer.WriteLine(json);
            recordsSinceFlush += 1;
            EvidenceLineWritten?.Invoke(json);
            if (recordsSinceFlush >= Mathf.Max(1, durableFlushIntervalRecords))
            {
                FlushDurably();
            }
        }

        private void FlushDurably()
        {
            if (writer == null)
            {
                return;
            }

            writer.Flush();
            stream.Flush(true);
            recordsSinceFlush = 0;
        }
    }
}
