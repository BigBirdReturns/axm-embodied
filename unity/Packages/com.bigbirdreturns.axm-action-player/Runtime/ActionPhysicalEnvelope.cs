using System;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public readonly struct ActionPhysicalEnvelopeStatus
    {
        public ActionPhysicalEnvelopeStatus(bool accepted, string reason, string envelopeDigest)
        {
            Accepted = accepted;
            Reason = reason ?? string.Empty;
            EnvelopeDigest = envelopeDigest ?? string.Empty;
        }

        public bool Accepted { get; }
        public string Reason { get; }
        public string EnvelopeDigest { get; }
    }

    public interface IActionPhysicalEnvelopeProvider
    {
        bool TryEvaluateActionEnvelope(out ActionPhysicalEnvelopeStatus status);
    }

    public abstract class ActionPhysicalEnvelopeProviderBase : MonoBehaviour, IActionPhysicalEnvelopeProvider
    {
        public abstract bool TryEvaluateActionEnvelope(out ActionPhysicalEnvelopeStatus status);
    }

    public sealed class TransformBoxActionEnvelopeProvider : ActionPhysicalEnvelopeProviderBase
    {
        [SerializeField] private Transform trackedHead;
        [SerializeField] private Transform volumeOrigin;
        [SerializeField] private Vector3 halfExtentsMeters = new Vector3(1.25f, 1.25f, 1.25f);
        [SerializeField, Min(0f)] private float safetyMarginMeters = 0.15f;
        [SerializeField] private string envelopeDigest = "local-transform-box";
        [SerializeField] private bool trackingAvailable = true;

        public override bool TryEvaluateActionEnvelope(out ActionPhysicalEnvelopeStatus status)
        {
            if (!trackingAvailable)
            {
                status = new ActionPhysicalEnvelopeStatus(false, "tracking-unavailable", envelopeDigest);
                return true;
            }

            Transform head = trackedHead == null && Camera.main != null ? Camera.main.transform : trackedHead;
            Transform origin = volumeOrigin == null ? transform : volumeOrigin;
            if (head == null)
            {
                status = new ActionPhysicalEnvelopeStatus(false, "tracked-head-absent", envelopeDigest);
                return true;
            }

            Vector3 local = origin.InverseTransformPoint(head.position);
            Vector3 acceptedExtents = new Vector3(
                Mathf.Max(0f, halfExtentsMeters.x - safetyMarginMeters),
                Mathf.Max(0f, halfExtentsMeters.y - safetyMarginMeters),
                Mathf.Max(0f, halfExtentsMeters.z - safetyMarginMeters));
            bool inside = Mathf.Abs(local.x) <= acceptedExtents.x
                && Mathf.Abs(local.y) <= acceptedExtents.y
                && Mathf.Abs(local.z) <= acceptedExtents.z;
            status = new ActionPhysicalEnvelopeStatus(
                inside,
                inside ? "accepted" : "guardian-margin-breached",
                envelopeDigest);
            return true;
        }
    }

    public sealed class ActionPhysicalEnvelopeController : MonoBehaviour
    {
        [SerializeField] private ActionBridgeDriver driver;
        [SerializeField] private ActionPlacementRoot placementRoot;
        [SerializeField] private MonoBehaviour envelopeProviderComponent;
        [SerializeField] private ActionEvidenceRecorder evidenceRecorder;
        [SerializeField, Min(0.01f)] private float evaluationIntervalSeconds = 0.05f;
        [SerializeField] private bool requirePlacement = true;
        [SerializeField] private bool pauseOnUnknownEnvelope = true;

        private IActionPhysicalEnvelopeProvider envelopeProvider;
        private float nextEvaluation;
        private bool paused;
        private string reason = string.Empty;
        private string envelopeDigest = string.Empty;

        public event Action<bool, string> EnvelopePauseChanged;

        public bool IsPaused => paused;
        public string Reason => reason;
        public string EnvelopeDigest => envelopeDigest;

        private void Awake()
        {
            envelopeProvider = envelopeProviderComponent as IActionPhysicalEnvelopeProvider;
            if (envelopeProviderComponent != null && envelopeProvider == null)
            {
                throw new InvalidOperationException("Physical envelope provider must implement IActionPhysicalEnvelopeProvider.");
            }
        }

        private void Update()
        {
            if (Time.unscaledTime < nextEvaluation)
            {
                return;
            }

            nextEvaluation = Time.unscaledTime + Mathf.Max(0.01f, evaluationIntervalSeconds);
            Evaluate();
        }

        public void SetEnvelopeProvider(MonoBehaviour provider)
        {
            IActionPhysicalEnvelopeProvider candidate = provider as IActionPhysicalEnvelopeProvider;
            if (provider != null && candidate == null)
            {
                throw new ArgumentException("Envelope provider must implement IActionPhysicalEnvelopeProvider.", nameof(provider));
            }

            envelopeProviderComponent = provider;
            envelopeProvider = candidate;
            Evaluate();
        }

        public void Evaluate()
        {
            bool accepted = true;
            string nextReason = "accepted";
            string nextDigest = envelopeDigest;

            if (requirePlacement && placementRoot != null && !placementRoot.IsPlacementValid)
            {
                accepted = false;
                nextReason = "placement-invalid";
            }
            else if (envelopeProvider == null)
            {
                accepted = !pauseOnUnknownEnvelope;
                nextReason = accepted ? "envelope-not-required" : "envelope-unavailable";
            }
            else if (!envelopeProvider.TryEvaluateActionEnvelope(out ActionPhysicalEnvelopeStatus status))
            {
                accepted = !pauseOnUnknownEnvelope;
                nextReason = accepted ? "envelope-provider-deferred" : "envelope-provider-failed";
            }
            else
            {
                accepted = status.Accepted;
                nextReason = status.Reason;
                nextDigest = status.EnvelopeDigest;
            }

            envelopeDigest = nextDigest ?? string.Empty;
            reason = nextReason ?? string.Empty;
            evidenceRecorder?.SetPhysicalEnvelopeDigest(envelopeDigest);
            evidenceRecorder?.SetTrackingState(accepted ? "tracked" : reason);

            bool nextPaused = !accepted;
            if (driver != null)
            {
                driver.SetPhysicalPause(nextPaused);
            }

            if (paused != nextPaused)
            {
                paused = nextPaused;
                EnvelopePauseChanged?.Invoke(paused, reason);
            }
        }
    }
}
