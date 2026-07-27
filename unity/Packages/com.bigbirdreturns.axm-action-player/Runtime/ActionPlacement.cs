using System;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public enum ActionPresentationScaleMode
    {
        Tabletop,
        LifeSize
    }

    public readonly struct ActionPlacementPose
    {
        public ActionPlacementPose(
            bool isValid,
            Pose pose,
            Vector2 planeExtentMeters,
            string anchorId,
            float trackingQuality)
        {
            IsValid = isValid;
            Pose = pose;
            PlaneExtentMeters = planeExtentMeters;
            AnchorId = anchorId ?? string.Empty;
            TrackingQuality = Mathf.Clamp01(trackingQuality);
        }

        public bool IsValid { get; }
        public Pose Pose { get; }
        public Vector2 PlaneExtentMeters { get; }
        public string AnchorId { get; }
        public float TrackingQuality { get; }
    }

    public interface IActionPlacementProvider
    {
        bool TryGetActionPlacement(out ActionPlacementPose placement);
    }

    public abstract class ActionPlacementProviderBase : MonoBehaviour, IActionPlacementProvider
    {
        public abstract bool TryGetActionPlacement(out ActionPlacementPose placement);
    }

    public sealed class FixedActionPlacementProvider : ActionPlacementProviderBase
    {
        [SerializeField] private Transform placementTransform;
        [SerializeField] private Vector2 planeExtentMeters = new Vector2(1.2f, 1.2f);
        [SerializeField] private string anchorId = "fixed-origin";
        [SerializeField, Range(0f, 1f)] private float trackingQuality = 1f;
        [SerializeField] private bool valid = true;

        public override bool TryGetActionPlacement(out ActionPlacementPose placement)
        {
            Transform source = placementTransform == null ? transform : placementTransform;
            placement = new ActionPlacementPose(
                valid,
                new Pose(source.position, source.rotation),
                planeExtentMeters,
                anchorId,
                trackingQuality);
            return valid;
        }
    }

    public sealed class ActionPlacementRoot : MonoBehaviour
    {
        [SerializeField] private MonoBehaviour placementProviderComponent;
        [SerializeField] private Transform arenaRoot;
        [SerializeField] private ActionPresentationScaleMode scaleMode = ActionPresentationScaleMode.Tabletop;
        [SerializeField, Min(0.1f)] private float tabletopTargetDiameterMeters = 0.9f;
        [SerializeField, Min(1f)] private float lifeSizeSimulationUnitsPerMeter = 1000f;
        [SerializeField, Range(0f, 1f)] private float minimumTrackingQuality = 0.5f;
        [SerializeField, Range(0.1f, 1f)] private float maximumPlaneUseFraction = 0.8f;
        [SerializeField] private bool hideArenaWhenInvalid = true;

        private IActionPlacementProvider placementProvider;
        private ActionSpecWire spec;
        private bool valid;
        private string anchorId = string.Empty;
        private float metersPerSimulationUnit = 0.001f;

        public event Action<bool> PlacementValidityChanged;
        public event Action<string> AnchorChanged;

        public bool IsPlacementValid => valid;
        public string AnchorId => anchorId;
        public float MetersPerSimulationUnit => metersPerSimulationUnit;
        public Transform ArenaRoot => arenaRoot == null ? transform : arenaRoot;
        public ActionPresentationScaleMode ScaleMode => scaleMode;

        private void Awake()
        {
            placementProvider = placementProviderComponent as IActionPlacementProvider;
            if (placementProviderComponent != null && placementProvider == null)
            {
                throw new InvalidOperationException("Placement provider must implement IActionPlacementProvider.");
            }

            if (arenaRoot == null)
            {
                arenaRoot = transform;
            }

            arenaRoot.localScale = Vector3.one;
        }

        private void LateUpdate()
        {
            RefreshPlacement();
        }

        public void SetPlacementProvider(MonoBehaviour provider)
        {
            IActionPlacementProvider candidate = provider as IActionPlacementProvider;
            if (provider != null && candidate == null)
            {
                throw new ArgumentException("Placement provider must implement IActionPlacementProvider.", nameof(provider));
            }

            placementProviderComponent = provider;
            placementProvider = candidate;
            RefreshPlacement();
        }

        public void BindSpec(ActionSpecWire actionSpec)
        {
            if (actionSpec == null || actionSpec.arena == null || actionSpec.arena.radius <= 0)
            {
                throw new ArgumentException("Action spec must contain a positive arena radius.", nameof(actionSpec));
            }

            spec = actionSpec;
            RefreshPlacement();
        }

        public void Configure(
            ActionPresentationScaleMode mode,
            float targetDiameterMeters,
            float simulationUnitsPerMeter)
        {
            scaleMode = mode;
            tabletopTargetDiameterMeters = Mathf.Max(0.1f, targetDiameterMeters);
            lifeSizeSimulationUnitsPerMeter = Mathf.Max(1f, simulationUnitsPerMeter);
            RefreshPlacement();
        }

        public Vector3 MapSimulationPosition(int x, int y, float elevationMeters = 0f)
        {
            return new Vector3(
                x * metersPerSimulationUnit,
                elevationMeters,
                y * metersPerSimulationUnit);
        }

        private void RefreshPlacement()
        {
            ActionPlacementPose placement;
            bool hasPlacement;
            if (placementProvider == null)
            {
                placement = new ActionPlacementPose(
                    true,
                    new Pose(ArenaRoot.position, ArenaRoot.rotation),
                    Vector2.zero,
                    "unbound-origin",
                    1f);
                hasPlacement = true;
            }
            else
            {
                hasPlacement = placementProvider.TryGetActionPlacement(out placement);
            }

            bool nextValid = hasPlacement
                && placement.IsValid
                && placement.TrackingQuality >= minimumTrackingQuality;

            if (nextValid)
            {
                ArenaRoot.SetPositionAndRotation(placement.Pose.position, placement.Pose.rotation);
                ArenaRoot.localScale = Vector3.one;
                UpdateScale(placement.PlaneExtentMeters);

                if (!string.Equals(anchorId, placement.AnchorId, StringComparison.Ordinal))
                {
                    anchorId = placement.AnchorId;
                    AnchorChanged?.Invoke(anchorId);
                }
            }

            if (hideArenaWhenInvalid && ArenaRoot.gameObject.activeSelf != nextValid)
            {
                ArenaRoot.gameObject.SetActive(nextValid);
            }

            if (valid != nextValid)
            {
                valid = nextValid;
                PlacementValidityChanged?.Invoke(valid);
            }
        }

        private void UpdateScale(Vector2 planeExtentMeters)
        {
            if (spec == null || spec.arena == null || spec.arena.radius <= 0)
            {
                metersPerSimulationUnit = 1f / Mathf.Max(1f, lifeSizeSimulationUnitsPerMeter);
                return;
            }

            if (scaleMode == ActionPresentationScaleMode.LifeSize)
            {
                metersPerSimulationUnit = 1f / Mathf.Max(1f, lifeSizeSimulationUnitsPerMeter);
                return;
            }

            float diameter = tabletopTargetDiameterMeters;
            if (planeExtentMeters.x > 0.01f && planeExtentMeters.y > 0.01f)
            {
                float available = Mathf.Min(planeExtentMeters.x, planeExtentMeters.y)
                    * Mathf.Clamp(maximumPlaneUseFraction, 0.1f, 1f);
                diameter = Mathf.Min(diameter, available);
            }

            metersPerSimulationUnit = Mathf.Max(0.000001f, diameter / (spec.arena.radius * 2f));
        }
    }
}
