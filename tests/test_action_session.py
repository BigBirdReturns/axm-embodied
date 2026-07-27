from __future__ import annotations

import json
from pathlib import Path

import pytest

from axm_embodied.action_session import (
    ActionSessionError,
    ActionSessionJournal,
    CANDIDATE_FORMAT,
    OBSERVATION_FORMAT,
    RECEIPT_FORMAT,
    SESSION_FORMAT,
)

ARC = "cart1_" + "a" * 64
SPEC = "actspec1_" + "b" * 64
JOB = "unityjob1_" + "c" * 64
RECEIPT = "actreceipt1_" + "d" * 64


def create_journal(tmp_path: Path) -> ActionSessionJournal:
    return ActionSessionJournal.create(
        tmp_path / "session",
        session_id="frog-pit-001",
        arc_digest=ARC,
        action_spec_digest=SPEC,
        device_id="quest-3-fixture",
        job_digest=JOB,
        generated_at="2026-07-26T00:00:00Z",
    )


def observation(**changes):
    value = {
        "format": OBSERVATION_FORMAT,
        "generatedAt": "2026-07-26T00:00:05Z",
        "reason": "guardian-clearance",
        "actionSpecDigest": SPEC,
        "actionTick": 120,
        "headX": 1.0,
        "headY": 1.7,
        "headZ": -0.5,
        "displacementMeters": 0.0,
        "boundaryClearanceMeters": 0.2,
        "boundaryKnown": True,
        "applicationFocused": True,
        "actionOutcome": "uncommitted",
        "authority": "physical safety stop only",
    }
    value.update(changes)
    return value


def candidate(**changes):
    value = {
        "format": CANDIDATE_FORMAT,
        "sourceReceiptFormat": RECEIPT_FORMAT,
        "runtimeVersion": "1.0.0",
        "arcDigest": ARC,
        "challengeId": "frog-pit",
        "difficultyModeId": None,
        "actionSpecDigest": SPEC,
        "cycle": 3,
        "seed": 7,
        "controlledAgentId": "agent-a",
        "partyAgentIds": ["agent-a"],
        "trace": [
            {
                "ticks": 2,
                "input": {"moveX": 1, "moveY": 0, "aimX": 1, "aimY": 0, "buttons": 0},
            },
            {
                "ticks": 1,
                "input": {"moveX": 0, "moveY": 0, "aimX": 1, "aimY": 0, "buttons": 1},
            },
        ],
        "totalTicks": 3,
        "provisionalResult": {
            "outcome": "success",
            "completedObjectiveIds": ["clear-frogs"],
            "objectives": [{"id": "clear-frogs", "defeated": 1, "target": 1, "completed": True}],
            "playerHealth": 8,
            "playerDefeated": False,
            "totalTicks": 3,
            "stats": {
                "hitsLanded": 1,
                "heavyHits": 0,
                "damageTaken": 0,
                "parries": 0,
                "dodgedAttacks": 0,
                "enemiesDefeated": 1,
            },
        },
        "authority": "Arc replay required",
    }
    value.update(changes)
    return value


def receipt(**changes):
    value = {
        "format": RECEIPT_FORMAT,
        "runtimeVersion": "1.0.0",
        "arcDigest": ARC,
        "actionSpecDigest": SPEC,
        "traceDigest": "acttrace1_" + "e" * 64,
        "receiptDigest": RECEIPT,
        "challengeId": "frog-pit",
        "cycle": 3,
        "seed": 7,
        "result": {
            "outcome": "success",
            "completedObjectiveIds": ["clear-frogs"],
        },
    }
    value.update(changes)
    return value


def test_physical_stop_is_recorded_without_campaign_effect(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    event = journal.append_observation(observation(), source_path="action-safety.json")
    verified = journal.verify()

    assert event["kind"] == "physical_session_stopped"
    assert event["payload"]["campaignEffect"] is None
    assert verified.stopped_observations == 1
    assert verified.accepted_receipt_digest is None


def test_observation_cannot_claim_action_failure(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)

    with pytest.raises(ActionSessionError, match="may not claim"):
        journal.append_observation(observation(actionOutcome="failure"))


def test_candidate_is_provisional_and_receipt_is_arc_authoritative(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    candidate_event = journal.attach_candidate(candidate(), source_path="candidate.json")
    receipt_event = journal.attach_receipt(receipt(), source_path="receipt.json")
    verified = journal.verify()

    assert candidate_event["payload"]["acceptedOutcome"] is None
    assert candidate_event["payload"]["authority"] == "Arc replay required"
    assert receipt_event["payload"]["acceptedOutcome"] == "success"
    assert receipt_event["payload"]["authority"] == "Arc replay verified"
    assert verified.provisional_candidate_digest
    assert verified.accepted_receipt_digest


def test_candidate_trace_must_cover_total_ticks_exactly(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)

    with pytest.raises(ActionSessionError, match="does not cover totalTicks"):
        journal.attach_candidate(candidate(totalTicks=4))


def test_candidate_identity_mismatch_is_refused(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)

    with pytest.raises(ActionSessionError, match="identity differs"):
        journal.attach_candidate(candidate(actionSpecDigest="actspec1_" + "f" * 64))


def test_receipt_cannot_precede_candidate(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)

    with pytest.raises(ActionSessionError, match="cannot precede"):
        journal.attach_receipt(receipt())


def test_receipt_identity_mismatch_is_refused(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    journal.attach_candidate(candidate())

    with pytest.raises(ActionSessionError, match="identity differs"):
        journal.attach_receipt(receipt(arcDigest="cart1_" + "0" * 64))


def test_tampered_event_payload_breaks_chain_verification(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    journal.append_observation(observation())
    lines = journal.events_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    event["payload"]["observation"]["reason"] = "fabricated"
    lines[-1] = json.dumps(event, sort_keys=True, separators=(",", ":"))
    journal.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ActionSessionError, match="invalid digest"):
        journal.verify()


def test_capture_is_evidence_without_semantic_authority(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    event = journal.append_capture(
        stream="head-camera",
        path="streams/head-camera/frame-0001.webp",
        sha256="1" * 64,
        media_type="image/webp",
        byte_length=1024,
        action_tick=15,
        timestamp="2026-07-26T00:00:01Z",
    )

    assert event["kind"] == "capture_recorded"
    assert event["payload"]["semanticAuthority"] is None
    journal.verify()


def test_genesis_shard_only_claims_action_outcome_after_arc_receipt(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    journal.attach_candidate(candidate())
    before = journal.to_genesis_shard()
    journal.attach_receipt(receipt())
    after = journal.to_genesis_shard()

    assert before["sourceFormat"] == SESSION_FORMAT
    assert before["authority"]["actionOutcome"] is False
    assert before["authority"]["campaignMutation"] is False
    assert after["authority"]["actionOutcome"] is True
    assert after["authority"]["actionOutcomeAuthority"] == "attached Arc receipt"
    assert after["authority"]["campaignMutation"] is False


def test_manifest_and_event_head_are_exact(tmp_path: Path) -> None:
    journal = create_journal(tmp_path)
    journal.append_observation(observation())
    verified = journal.verify()
    manifest = json.loads(journal.manifest_path.read_text(encoding="utf-8"))

    assert manifest["eventCount"] == verified.event_count
    assert manifest["headDigest"] == verified.head_digest
    assert len(verified.head_digest) == 64
