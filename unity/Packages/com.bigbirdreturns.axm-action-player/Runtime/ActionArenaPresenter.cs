using System;
using System.Collections.Generic;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    [Serializable]
    public sealed class ActionEnemyPrefabBinding
    {
        public string kit = string.Empty;
        public GameObject prefab;
    }

    public sealed class ActionArenaPresenter : MonoBehaviour
    {
        [SerializeField] private ActionBridgeDriver driver;
        [SerializeField] private ActionPlacementRoot placementRoot;
        [SerializeField] private Transform actorRoot;
        [SerializeField] private GameObject playerPrefab;
        [SerializeField] private ActionEnemyPrefabBinding[] enemyPrefabs = Array.Empty<ActionEnemyPrefabBinding>();
        [SerializeField, Min(0f)] private float actorElevationMeters = 0.02f;
        [SerializeField, Min(0.1f)] private float interpolationSharpness = 18f;
        [SerializeField, Min(0.01f)] private float fallbackActorHeightMeters = 0.12f;
        [SerializeField] private bool createFallbackPrimitives = true;

        private sealed class ActorView
        {
            public GameObject GameObject;
            public Transform Transform;
            public Vector3 TargetPosition;
            public Quaternion TargetRotation;
            public string Kit;
            public int LastSeenTick;
        }

        private readonly Dictionary<string, ActorView> views = new Dictionary<string, ActorView>(StringComparer.Ordinal);
        private readonly Dictionary<string, GameObject> enemyPrefabByKit = new Dictionary<string, GameObject>(StringComparer.Ordinal);
        private readonly Dictionary<string, Stack<GameObject>> poolByKit = new Dictionary<string, Stack<GameObject>>(StringComparer.Ordinal);
        private ActionSpecWire spec;
        private int latestTick = -1;

        public int VisibleActorCount => views.Count;
        public int LatestTick => latestTick;

        private void Awake()
        {
            if (actorRoot == null)
            {
                actorRoot = transform;
            }

            enemyPrefabByKit.Clear();
            for (int index = 0; index < enemyPrefabs.Length; index += 1)
            {
                ActionEnemyPrefabBinding binding = enemyPrefabs[index];
                if (binding == null || string.IsNullOrWhiteSpace(binding.kit) || binding.prefab == null)
                {
                    continue;
                }

                enemyPrefabByKit[binding.kit] = binding.prefab;
            }
        }

        private void OnEnable()
        {
            if (driver == null)
            {
                return;
            }

            driver.SessionOpened += OnSessionOpened;
            driver.SnapshotReceived += OnSnapshot;
            driver.SessionCompleted += OnTerminal;
        }

        private void OnDisable()
        {
            if (driver == null)
            {
                return;
            }

            driver.SessionOpened -= OnSessionOpened;
            driver.SnapshotReceived -= OnSnapshot;
            driver.SessionCompleted -= OnTerminal;
        }

        private void Update()
        {
            float blend = 1f - Mathf.Exp(-Mathf.Max(0.1f, interpolationSharpness) * Time.unscaledDeltaTime);
            foreach (ActorView view in views.Values)
            {
                if (view.Transform == null)
                {
                    continue;
                }

                view.Transform.localPosition = Vector3.Lerp(view.Transform.localPosition, view.TargetPosition, blend);
                view.Transform.localRotation = Quaternion.Slerp(view.Transform.localRotation, view.TargetRotation, blend);
            }
        }

        private void OnSessionOpened(ActionOpenedMessage opened)
        {
            spec = opened.spec;
            latestTick = -1;
            placementRoot?.BindSpec(spec);
            ClearAllViews();
            if (opened.snapshot != null)
            {
                Present(opened.snapshot);
            }
        }

        private void OnSnapshot(ActionSnapshotMessage snapshot)
        {
            Present(snapshot);
        }

        private void OnTerminal(ActionTerminalMessage terminal)
        {
            if (terminal != null && terminal.snapshot != null)
            {
                Present(terminal.snapshot);
            }
        }

        public void Present(ActionSnapshotMessage snapshot)
        {
            if (snapshot == null || placementRoot == null)
            {
                return;
            }

            if (latestTick >= 0 && snapshot.tick < latestTick)
            {
                return;
            }

            latestTick = snapshot.tick;
            HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);

            if (snapshot.player != null)
            {
                string playerId = "player";
                seen.Add(playerId);
                ActorView playerView = GetOrCreate(playerId, "player", true);
                SetTarget(
                    playerView,
                    snapshot.player.x,
                    snapshot.player.y,
                    snapshot.player.facingX,
                    snapshot.player.facingY,
                    latestTick,
                    snapshot.player.mode);
            }

            ActionEnemySnapshot[] enemies = snapshot.enemies ?? Array.Empty<ActionEnemySnapshot>();
            for (int index = 0; index < enemies.Length; index += 1)
            {
                ActionEnemySnapshot enemy = enemies[index];
                if (enemy == null || string.IsNullOrWhiteSpace(enemy.id))
                {
                    continue;
                }

                seen.Add(enemy.id);
                ActorView enemyView = GetOrCreate(enemy.id, enemy.kit, false);
                int facingX = snapshot.player == null ? 0 : Math.Sign(snapshot.player.x - enemy.x);
                int facingY = snapshot.player == null ? 1 : Math.Sign(snapshot.player.y - enemy.y);
                SetTarget(enemyView, enemy.x, enemy.y, facingX, facingY, latestTick, enemy.mode);
                enemyView.GameObject.SetActive(!string.Equals(enemy.mode, "defeated", StringComparison.Ordinal));
            }

            List<string> stale = new List<string>();
            foreach (KeyValuePair<string, ActorView> pair in views)
            {
                if (!seen.Contains(pair.Key))
                {
                    stale.Add(pair.Key);
                }
            }

            for (int index = 0; index < stale.Count; index += 1)
            {
                Release(stale[index]);
            }
        }

        private ActorView GetOrCreate(string id, string kit, bool player)
        {
            if (views.TryGetValue(id, out ActorView existing))
            {
                return existing;
            }

            GameObject instance = TakeFromPool(kit);
            if (instance == null)
            {
                GameObject prefab = player ? playerPrefab : ResolveEnemyPrefab(kit);
                if (prefab != null)
                {
                    instance = Instantiate(prefab, actorRoot);
                }
                else if (createFallbackPrimitives)
                {
                    instance = CreateFallbackPrimitive(kit, player);
                    instance.transform.SetParent(actorRoot, false);
                }
                else
                {
                    instance = new GameObject(player ? "Action Player" : "Action Enemy " + kit);
                    instance.transform.SetParent(actorRoot, false);
                }
            }

            instance.name = player ? "Action Player" : "Action Enemy " + id;
            instance.SetActive(true);
            ActorView view = new ActorView
            {
                GameObject = instance,
                Transform = instance.transform,
                TargetPosition = instance.transform.localPosition,
                TargetRotation = instance.transform.localRotation,
                Kit = kit,
                LastSeenTick = latestTick
            };
            views[id] = view;
            return view;
        }

        private void SetTarget(
            ActorView view,
            int x,
            int y,
            int facingX,
            int facingY,
            int tick,
            string mode)
        {
            view.TargetPosition = placementRoot.MapSimulationPosition(x, y, actorElevationMeters);
            Vector3 facing = new Vector3(facingX, 0f, facingY);
            if (facing.sqrMagnitude > 0.01f)
            {
                view.TargetRotation = Quaternion.LookRotation(facing.normalized, Vector3.up);
            }

            view.LastSeenTick = tick;
            float pulse = string.Equals(mode, "telegraph", StringComparison.Ordinal)
                || string.Equals(mode, "heavy", StringComparison.Ordinal)
                ? 1.08f
                : 1f;
            view.Transform.localScale = Vector3.one * pulse;
        }

        private GameObject ResolveEnemyPrefab(string kit)
        {
            enemyPrefabByKit.TryGetValue(kit ?? string.Empty, out GameObject prefab);
            return prefab;
        }

        private GameObject TakeFromPool(string kit)
        {
            string key = kit ?? string.Empty;
            if (!poolByKit.TryGetValue(key, out Stack<GameObject> pool) || pool.Count == 0)
            {
                return null;
            }

            return pool.Pop();
        }

        private void Release(string id)
        {
            if (!views.TryGetValue(id, out ActorView view))
            {
                return;
            }

            views.Remove(id);
            if (view.GameObject == null)
            {
                return;
            }

            view.GameObject.SetActive(false);
            string key = view.Kit ?? string.Empty;
            if (!poolByKit.TryGetValue(key, out Stack<GameObject> pool))
            {
                pool = new Stack<GameObject>();
                poolByKit[key] = pool;
            }
            pool.Push(view.GameObject);
        }

        private void ClearAllViews()
        {
            List<string> ids = new List<string>(views.Keys);
            for (int index = 0; index < ids.Count; index += 1)
            {
                Release(ids[index]);
            }
        }

        private GameObject CreateFallbackPrimitive(string kit, bool player)
        {
            PrimitiveType primitive = PrimitiveType.Capsule;
            Vector3 scale = new Vector3(0.06f, fallbackActorHeightMeters * 0.5f, 0.06f);

            if (!player)
            {
                switch (kit)
                {
                    case "swarm":
                        primitive = PrimitiveType.Sphere;
                        scale = Vector3.one * 0.065f;
                        break;
                    case "duelist":
                        primitive = PrimitiveType.Cylinder;
                        scale = new Vector3(0.055f, fallbackActorHeightMeters * 0.45f, 0.055f);
                        break;
                    case "hexer":
                        primitive = PrimitiveType.Cube;
                        scale = new Vector3(0.07f, fallbackActorHeightMeters, 0.07f);
                        break;
                    case "breaker":
                        primitive = PrimitiveType.Cube;
                        scale = new Vector3(0.11f, fallbackActorHeightMeters * 1.2f, 0.11f);
                        break;
                }
            }

            GameObject result = GameObject.CreatePrimitive(primitive);
            Collider collider = result.GetComponent<Collider>();
            if (collider != null)
            {
                Destroy(collider);
            }
            result.transform.localScale = scale;
            return result;
        }
    }
}
