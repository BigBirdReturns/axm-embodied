using System;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public interface IActionSceneAssetResolver
    {
        GameObject ResolveActionPrefab(string assetId);
    }

    public abstract class ActionSceneAssetResolverBase : MonoBehaviour, IActionSceneAssetResolver
    {
        public abstract GameObject ResolveActionPrefab(string assetId);
    }

    public sealed class ActionSceneCompilerAdapter : MonoBehaviour
    {
        [SerializeField] private ActionPlacementRoot placementRoot;
        [SerializeField] private ActionArenaPresenter presenter;
        [SerializeField] private MonoBehaviour assetResolverComponent;
        [SerializeField] private TextAsset defaultSceneJob;

        private IActionSceneAssetResolver assetResolver;
        private ActionSceneJob activeJob;

        public ActionSceneJob ActiveJob => activeJob;

        private void Awake()
        {
            assetResolver = assetResolverComponent as IActionSceneAssetResolver;
            if (assetResolverComponent != null && assetResolver == null)
            {
                throw new InvalidOperationException("Action scene asset resolver must implement IActionSceneAssetResolver.");
            }

            if (defaultSceneJob != null)
            {
                ApplyJobJson(defaultSceneJob.text);
            }
        }

        public void SetAssetResolver(MonoBehaviour resolver)
        {
            IActionSceneAssetResolver candidate = resolver as IActionSceneAssetResolver;
            if (resolver != null && candidate == null)
            {
                throw new ArgumentException("Resolver must implement IActionSceneAssetResolver.", nameof(resolver));
            }

            assetResolverComponent = resolver;
            assetResolver = candidate;
        }

        public ActionSceneJob ApplyJobJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("Action scene job JSON is empty.", nameof(json));
            }

            ActionSceneJob job = JsonUtility.FromJson<ActionSceneJob>(json);
            Validate(job);
            activeJob = job;

            if (placementRoot != null)
            {
                ActionPresentationScaleMode mode = string.Equals(
                    job.presentation.mode,
                    "life-size",
                    StringComparison.Ordinal)
                    ? ActionPresentationScaleMode.LifeSize
                    : ActionPresentationScaleMode.Tabletop;
                placementRoot.Configure(
                    mode,
                    job.presentation.targetDiameterMeters,
                    job.presentation.simulationUnitsPerMeter);
            }

            // Asset ids remain presentation choices. The presenter may already have
            // serialized bindings, while the project scene compiler may resolve and
            // assign richer prefabs through its own durable asset registry.
            if (assetResolver != null)
            {
                assetResolver.ResolveActionPrefab(job.presentation.playerPrefab);
                ActionEnemyPrefabReference[] enemies = job.presentation.enemyPrefabs
                    ?? Array.Empty<ActionEnemyPrefabReference>();
                for (int index = 0; index < enemies.Length; index += 1)
                {
                    if (enemies[index] != null)
                    {
                        assetResolver.ResolveActionPrefab(enemies[index].prefab);
                    }
                }
            }

            return job;
        }

        public static void Validate(ActionSceneJob job)
        {
            if (job == null)
            {
                throw new FormatException("Action scene job is absent.");
            }

            if (!string.Equals(job.format, ActionBridgeProtocol.SceneJobFormat, StringComparison.Ordinal))
            {
                throw new FormatException("Unsupported action scene job format: " + job.format);
            }

            if (job.presentation == null)
            {
                throw new FormatException("Action scene job lacks presentation settings.");
            }

            bool tabletop = string.Equals(job.presentation.mode, "tabletop", StringComparison.Ordinal);
            bool lifeSize = string.Equals(job.presentation.mode, "life-size", StringComparison.Ordinal);
            if (!tabletop && !lifeSize)
            {
                throw new FormatException("Action scene presentation mode must be tabletop or life-size.");
            }

            if (!float.IsFinite(job.presentation.targetDiameterMeters)
                || job.presentation.targetDiameterMeters < 0.1f
                || job.presentation.targetDiameterMeters > 20f)
            {
                throw new FormatException("Action scene target diameter must be between 0.1 and 20 meters.");
            }

            if (!float.IsFinite(job.presentation.simulationUnitsPerMeter)
                || job.presentation.simulationUnitsPerMeter < 1f
                || job.presentation.simulationUnitsPerMeter > 100000f)
            {
                throw new FormatException("Simulation units per meter must be between 1 and 100000.");
            }

            if (string.IsNullOrWhiteSpace(job.presentation.playerPrefab))
            {
                throw new FormatException("Action scene job lacks a player presentation id.");
            }

            ActionEnemyPrefabReference[] bindings = job.presentation.enemyPrefabs
                ?? Array.Empty<ActionEnemyPrefabReference>();
            for (int index = 0; index < bindings.Length; index += 1)
            {
                ActionEnemyPrefabReference binding = bindings[index];
                if (binding == null || string.IsNullOrWhiteSpace(binding.kit) || string.IsNullOrWhiteSpace(binding.prefab))
                {
                    throw new FormatException("Action scene enemy bindings require kit and prefab ids.");
                }
            }
        }
    }
}
