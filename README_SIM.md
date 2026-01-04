## Capsule simulator (Virtual Robot)

Use `tools/sim_robot.py` to generate fresh Phase A capsules on demand.

Example:

```bash
python tools/sim_robot.py my_runs 10
# Generates 10 capsules under my_runs/capsule-XXXXXXXX/
```

Each capsule includes:
- `meta.json`
- `events.jsonl` (canonical JSONL, UTF-8, LF)

Feed capsules into your compiler, then verify shards.
