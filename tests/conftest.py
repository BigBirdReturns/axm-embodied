"""Shared fixtures for the embodied suite: throwaway keys, capsules, envelope."""
from __future__ import annotations

from pathlib import Path

import pytest

from axm_build.sign import hybrid1_keygen

from axm_embodied.bounds import compile_bounds
from axm_embodied.gate import enroll_key
from axm_embodied.recorder import CapsuleRecorder
from axm_embodied.sim import mission_frames

FRAMES = 50
RESIDUAL_BYTES = 1024


@pytest.fixture(scope="session")
def school_keys() -> tuple[bytes, bytes]:
    """(public, secret) for the Drone School envelope publisher."""
    return hybrid1_keygen()


@pytest.fixture(scope="session")
def robot_keys() -> tuple[bytes, bytes]:
    """(public, secret) for the robot's incident publisher."""
    return hybrid1_keygen()


def record_mission(out_dir: Path, fault_at: int | None = None, seed: int = 7,
                   frames: int = FRAMES) -> Path:
    """Record one simulated mission straight through the recorder (no runtime)."""
    with CapsuleRecorder(out_dir, robot_id="test-unit") as rec:
        for fr in mission_frames(frames=frames, seed=seed, fault_at=fault_at,
                                 residual_bytes=RESIDUAL_BYTES):
            is_fault = fr.event is not None and fr.event.get("evt") == "wheel_slip"
            if is_fault:
                rec.trigger()
            rec.record_frame(
                fr.latents,
                "emergency_stop" if is_fault else fr.selected_action,
                fr.action_distribution,
                residual=fr.residual,
                event=fr.event,
            )
    return rec.path


@pytest.fixture(scope="session")
def bounds_shard(tmp_path_factory, school_keys) -> Path:
    """Training runs -> compiled + verified bounds shard (session-scoped)."""
    base = tmp_path_factory.mktemp("droneschool")
    training = base / "training"
    for i in range(3):
        record_mission(training, seed=100 + i)
    out = base / "bounds_shard"
    compile_bounds(training, out, school_keys[1], timestamp="2026-07-02T00:00:00Z")
    return out


@pytest.fixture(scope="session")
def governance(tmp_path_factory, school_keys) -> Path:
    """Governance dir with the school key enrolled and Tier-0 policy."""
    gov = tmp_path_factory.mktemp("governance")
    pub_path = gov / "school.pub.tmp"
    pub_path.write_bytes(school_keys[0])
    enroll_key(gov, pub_path, name="drone_school")
    pub_path.unlink()
    (gov / "local_policy.json").write_text('{"max_actuation_tier": 0}\n')
    return gov
