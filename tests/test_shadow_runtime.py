"""Shadow Runtime + Law Gate: the closed loop beyond the flight recorder.

training capsules -> signed envelope -> Law Gate arming -> per-frame
guard -> breach -> ESTOP + Flash Freeze -> incident shard citing the
envelope. Fail-closed at every seam.
"""
from __future__ import annotations

import json

import pytest

from axm_verify.logic import verify_shard

from axm_embodied.envelope import EnvelopeError, SafetyEnvelope
from axm_embodied.gate import GateError, LawGate
from axm_embodied.recorder import CapsuleRecorder
from axm_embodied.runtime import RuntimeState, ShadowRuntime, Verdict
from axm_embodied.sim import SAFE_ACTIONS, mission_frames

from conftest import RESIDUAL_BYTES


# ── Envelope ─────────────────────────────────────────────────────────────

def test_envelope_loads_from_verified_shard(bounds_shard, governance):
    anchor = next((governance / "trusted_keys").glob("*.pub"))
    env = SafetyEnvelope.load(bounds_shard, trusted_key_path=anchor)
    assert env.shard_id.startswith("sh1_")
    assert set(env.bounds) == set(SAFE_ACTIONS)
    assert all(0 < b < 1.0 for b in env.bounds.values())
    assert env.max_tier == 0


def test_envelope_rejects_wrong_trust_anchor(bounds_shard, tmp_path, robot_keys):
    wrong = tmp_path / "wrong.pub"
    wrong.write_bytes(robot_keys[0])
    with pytest.raises(EnvelopeError, match="failed verification"):
        SafetyEnvelope.load(bounds_shard, trusted_key_path=wrong)


def test_envelope_rejects_tampered_shard(bounds_shard, governance, tmp_path):
    import shutil
    tampered = tmp_path / "tampered"
    shutil.copytree(bounds_shard, tampered)
    claims = tampered / "graph" / "claims.jsonl"
    # Widen a bound by an order of magnitude — one byte of generosity.
    claims.write_bytes(claims.read_bytes().replace(b"0.8", b"8.8", 1))

    anchor = next((governance / "trusted_keys").glob("*.pub"))
    with pytest.raises(EnvelopeError, match="failed verification"):
        SafetyEnvelope.load(tampered, trusted_key_path=anchor)


# ── Law Gate ─────────────────────────────────────────────────────────────

def test_gate_authorizes_enrolled_publisher(bounds_shard, governance):
    clearance = LawGate(governance).authorize(bounds_shard)
    assert clearance.envelope.bounds
    assert clearance.max_actuation_tier == 0


def test_gate_refuses_unenrolled_publisher(bounds_shard, tmp_path, robot_keys):
    gov = tmp_path / "gov"
    from axm_embodied.gate import enroll_key
    other = tmp_path / "other.pub"
    other.write_bytes(robot_keys[0])       # enrolled key != shard publisher
    enroll_key(gov, other)
    with pytest.raises(GateError, match="not an enrolled trust anchor"):
        LawGate(gov).authorize(bounds_shard)


def test_gate_refuses_empty_trust_store(tmp_path):
    gov = tmp_path / "gov"
    gov.mkdir()
    (gov / "trust_store.json").write_text('{"trusted_publishers": []}')
    with pytest.raises(GateError, match="no trusted publishers"):
        LawGate(gov)


def test_gate_ignores_unenrolled_key_file_on_disk(bounds_shard, governance, tmp_path):
    """Dropping a .pub into trusted_keys/ without a trust_store entry is
    not enrollment."""
    import shutil
    gov = tmp_path / "gov"
    shutil.copytree(governance, gov)
    (gov / "trust_store.json").write_text(
        json.dumps({"trusted_publishers": ["0" * 64]})
    )
    with pytest.raises(GateError):
        LawGate(gov).authorize(bounds_shard)


def test_gate_enforces_actuation_tier_policy(bounds_shard, governance, tmp_path):
    import shutil
    gov = tmp_path / "gov"
    shutil.copytree(governance, gov)
    (gov / "local_policy.json").write_text('{"max_actuation_tier": -1}')
    with pytest.raises(GateError, match="Tier"):
        LawGate(gov).authorize(bounds_shard)


# ── Runtime ──────────────────────────────────────────────────────────────

def _armed_runtime(bounds_shard, governance, out_dir) -> ShadowRuntime:
    clearance = LawGate(governance).authorize(bounds_shard)
    recorder = CapsuleRecorder(out_dir, robot_id="test-unit")
    return ShadowRuntime(clearance, recorder)


def _run(runtime: ShadowRuntime, frames: int, fault_at=None, seed=42):
    decisions = []
    for fr in mission_frames(frames=frames, seed=seed, fault_at=fault_at,
                             residual_bytes=RESIDUAL_BYTES):
        decisions.append(runtime.guard(
            fr.latents, fr.selected_action, fr.action_distribution,
            residual=fr.residual, event=fr.event,
        ))
    return decisions


def test_clean_flight_all_frames_permitted(bounds_shard, governance, tmp_path):
    rt = _armed_runtime(bounds_shard, governance, tmp_path)
    decisions = _run(rt, frames=50)
    assert all(d.permitted for d in decisions)
    assert rt.state is RuntimeState.ARMED
    assert rt.seal() is None                       # clean flight: no incident
    assert (rt.recorder.path / "cam_residuals.bin").stat().st_size == 0


def test_breach_estops_and_stays_estopped(bounds_shard, governance, tmp_path):
    rt = _armed_runtime(bounds_shard, governance, tmp_path)
    decisions = _run(rt, frames=50, fault_at=20)

    assert all(d.permitted for d in decisions[:20])
    breach = decisions[20]
    assert breach.verdict is Verdict.ESTOP
    assert breach.l_inf > breach.bound
    assert rt.breach_frame == 20
    # Motors stay dead; recording continues gap-free.
    assert all(d.verdict is Verdict.ESTOP for d in decisions[20:])
    assert rt.recorder.frames_recorded == 50


def test_breach_seals_incident_shard_citing_envelope(
    bounds_shard, governance, tmp_path, robot_keys
):
    pub, key = robot_keys
    rt = _armed_runtime(bounds_shard, governance, tmp_path / "flight")
    _run(rt, frames=50, fault_at=20)

    incident = rt.seal(shard_out=tmp_path / "incident", secret_key=key)
    assert incident is not None
    assert incident.breach_frame == 20
    assert incident.shard_id and incident.shard_id.startswith("sh1_")
    assert incident.envelope_shard_id == rt.envelope.shard_id

    # The incident shard verifies independently...
    anchor = tmp_path / "robot.pub"
    anchor.write_bytes(pub)
    result = verify_shard(incident.shard_path, trusted_key_path=anchor)
    assert result["status"] == "PASS", result["errors"]
    assert "embodied@1" in result["profiles_checked"]

    # ...and its breach claim cites the exact envelope shard id.
    refs = [
        json.loads(line)
        for line in (incident.shard_path / "ext" / "references@1.jsonl")
        .read_text().splitlines()
    ]
    assert any(
        r["dst_shard_id"] == rt.envelope.shard_id and r["relation_type"] == "cites"
        for r in refs
    )

    # Flash Freeze put the cold stream on disk and into the shard.
    assert (incident.shard_path / "content" / "cam_residuals.bin").stat().st_size > 0

    # The breach event is on the record with the envelope id inline.
    events = (incident.capsule_path / "events.jsonl").read_text().splitlines()
    breach_events = [json.loads(l) for l in events if "envelope_breach" in l]
    assert breach_events and breach_events[0]["envelope_shard_id"] == rt.envelope.shard_id


def test_uncovered_action_class_fails_closed(bounds_shard, governance, tmp_path):
    """An action with no signed bound is forbidden motion, not a free pass."""
    from axm_embodied.sim import nominal_latents, vla_distribution
    import random

    rt = _armed_runtime(bounds_shard, governance, tmp_path)
    rng = random.Random(1)
    d = rt.guard(
        nominal_latents(rng), "warp_drive", vla_distribution(rng, "maintain_speed"),
    )
    assert d.verdict is Verdict.ESTOP
    assert "no signed bound" in d.reason
    assert rt.state is RuntimeState.ESTOP


def test_nonfinite_latents_fail_closed(bounds_shard, governance, tmp_path):
    import numpy as np
    from axm_embodied.sim import vla_distribution
    import random

    rt = _armed_runtime(bounds_shard, governance, tmp_path)
    garbage = np.full(64, np.nan, dtype=np.float32).tobytes()
    d = rt.guard(
        garbage, "maintain_speed",
        vla_distribution(random.Random(1), "maintain_speed"),
    )
    assert d.verdict is Verdict.ESTOP
    assert "non-finite" in d.reason
