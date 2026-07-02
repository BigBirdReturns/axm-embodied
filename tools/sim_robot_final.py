#!/usr/bin/env python3
"""Flash Freeze simulator — capsule generator harness.

The recorder itself lives in the library (`axm_embodied.recorder`); this
script only drives it with simulated missions (`axm_embodied.sim`). A
safe run leaves a 0-byte cold stream; a crash run injects a wheel-slip
physics excursion at frame 50 and triggers Flash Freeze exactly as the
Shadow Runtime would.

For the full enforcement loop (Law Gate, signed envelope, ESTOP, incident
shard), use `axm-runtime fly` instead.
"""
from __future__ import annotations

import argparse

from axm_embodied.recorder import CapsuleRecorder
from axm_embodied.sim import mission_frames


def generate_session(out_dir: str, crash: bool = False, frames: int = 100,
                     seed: int | None = None, robot_id: str = "sim-final") -> None:
    fault_at = frames // 2 if crash else None
    with CapsuleRecorder(out_dir, robot_id=robot_id) as rec:
        print(f"Generating: {rec.session_id} (Crash={crash})")
        for fr in mission_frames(frames=frames, seed=seed, fault_at=fault_at):
            is_fault = fr.event is not None and fr.event.get("evt") == "wheel_slip"
            if is_fault:
                # Tier-1 trigger: flush the pre-window BEFORE recording the
                # trigger frame so the frame lands inside the post-window.
                rec.trigger()
            rec.record_frame(
                fr.latents,
                "emergency_stop" if is_fault else fr.selected_action,
                fr.action_distribution,
                residual=fr.residual,
                event=fr.event,
            )
    print(f"  capsule: {rec.path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AXM Flash Freeze simulator")
    parser.add_argument("--out", default="capsules_final",
                        help="Output directory for capsules (default: capsules_final)")
    parser.add_argument("--crash", action="store_true",
                        help="Simulate a crash event (wheel_slip + emergency_stop)")
    parser.add_argument("--both", action="store_true",
                        help="Run both a safe and a crash session")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.both:
        generate_session(args.out, crash=False, frames=args.frames, seed=args.seed)
        generate_session(args.out, crash=True, frames=args.frames, seed=args.seed)
    else:
        generate_session(args.out, crash=args.crash, frames=args.frames, seed=args.seed)
