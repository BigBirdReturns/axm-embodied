import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

def get_timestamp(start_time: datetime, offset_seconds: float) -> str:
    t = start_time + timedelta(seconds=offset_seconds)
    return t.isoformat(timespec="milliseconds") + "Z"

def generate_capsule(output_dir: str) -> Path:
    robot_id = f"robot-{random.randint(100, 999)}"
    session_id = str(uuid.uuid4())
    start_time = datetime.utcnow()

    events = []

    # 1. Session Start
    events.append({
        "ts": get_timestamp(start_time, 0),
        "lvl": "INFO",
        "evt": "session_start",
        "robot_id": robot_id,
        "session_id": session_id
    })

    # 2. Normal Operation (Driving)
    t = 1.0
    for _ in range(5):
        events.append({
            "ts": get_timestamp(start_time, t),
            "lvl": "INFO",
            "evt": "cmd_vel",
            "vx": round(random.uniform(0.5, 1.5), 2),
            "wz": 0.0
        })
        t += 1.0

    # 3. The Anomaly (Wheel Slip)
    slip_time = t
    surface = random.choice(["wet_tile", "ice", "loose_gravel", "oil_slick"])
    slip_ratio = round(random.uniform(0.3, 0.9), 2)

    events.append({
        "ts": get_timestamp(start_time, slip_time),
        "lvl": "WARN",
        "evt": "wheel_slip",
        "wheel": "rear_left",
        "slip_ratio": slip_ratio,
        "surface": surface
    })

    # 4. The Reaction (Recovery)
    t += 0.05
    events.append({
        "ts": get_timestamp(start_time, t),
        "lvl": "INFO",
        "evt": "recovery_action",
        "action": "reduce_throttle",
        "value": 0.30
    })

    t += 0.1
    events.append({
        "ts": get_timestamp(start_time, t),
        "lvl": "INFO",
        "evt": "recovery_action",
        "action": "increase_traction_control",
        "value": 1.0
    })

    # 5. Resolution
    t += 1.5
    events.append({
        "ts": get_timestamp(start_time, t),
        "lvl": "INFO",
        "evt": "wheel_slip_cleared",
        "wheel": "rear_left",
        "slip_ratio": 0.05
    })

    # 6. Session End
    t += 5.0
    events.append({
        "ts": get_timestamp(start_time, t),
        "lvl": "INFO",
        "evt": "session_end",
        "ok": True
    })

    # --- WRITE CAPSULE ---
    out = Path(output_dir) / f"capsule-{session_id[:8]}"
    out.mkdir(parents=True, exist_ok=True)

    meta = {
        "robot_id": robot_id,
        "session_id": session_id,
        "started_at": get_timestamp(start_time, 0),
        "ended_at": get_timestamp(start_time, t),
        "event_log_encoding": "utf-8",
        "event_log_newline": "\n"
    }

    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with open(out / "events.jsonl", "wb") as f:
        for evt in events:
            # Canonical serialization for the log
            line = json.dumps(evt, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            f.write(line.encode("utf-8") + b"\n")

    print(f"GENERATED: {out}")
    return out

if __name__ == "__main__":
    import sys

    # Phase 1 usage (legacy):
    #   python tools/sim_robot.py OUT_DIR RUNS
    #
    # Phase 2 usage:
    #   python tools/sim_robot.py --phase2 OUT_DIR --runs 1 [--crash]

    args = [a for a in sys.argv[1:] if a]

    def pop_flag(arg_list: list[str], flag: str) -> tuple[bool, list[str]]:
        """Remove a boolean flag from an argv-style list."""
        if flag in arg_list:
            return True, [a for a in arg_list if a != flag]
        return False, arg_list

    phase2, args = pop_flag(args, "--phase2")
    crash, args = pop_flag(args, "--crash")

    runs = 1
    if "--runs" in args:
        i = args.index("--runs")
        if i + 1 >= len(args):
            raise SystemExit("--runs requires a value")
        runs = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    out = args[0] if len(args) > 0 else ("capsules_final" if phase2 else "simulated_capsules")

    if phase2:
        from sim_robot_final import generate_session
        for _ in range(runs):
            generate_session(out, crash=crash)
        raise SystemExit(0)

    # Phase 1 default behavior
    legacy_runs = runs
    for _ in range(legacy_runs):
        generate_capsule(out)
