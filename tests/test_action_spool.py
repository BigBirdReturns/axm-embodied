from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from axm_embodied.action_session import ActionSessionError, ActionSessionJournal
from axm_embodied.action_spool import ingest_spool

ARC = "cart1_" + "a" * 64
SPEC = "actspec1_" + "b" * 64
JOB = "unityjob1_" + "c" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_spool(tmp_path: Path) -> Path:
    spool = tmp_path / "spool"
    write_json(
        spool / "session-start.json",
        {
            "format": "rodoh-action-session-spool-start/1",
            "generatedAt": "2026-07-26T00:00:00Z",
            "sessionId": "frog-pit-001",
            "deviceId": "quest-3-fixture",
            "arcDigest": ARC,
            "actionSpecDigest": SPEC,
            "unityJobDigest": JOB,
            "unityVersion": "6000.0.66f2",
            "platform": "Android",
            "authority": "physical and provisional Unity source only",
        },
    )
    write_json(
        spool / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "frog-pit-001",
            "nextSequence": 1,
            "lastEntry": None,
        },
    )
    return spool


def observation() -> dict:
    return {
        "format": "rodoh-embodied-action-observation/1",
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


def candidate() -> dict:
    return {
        "format": "rodoh-action-execution-candidate/1",
        "sourceReceiptFormat": "axm-action-receipt/1",
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
            {"ticks": 2, "input": {"moveX": 1, "moveY": 0, "aimX": 1, "aimY": 0, "buttons": 0}},
            {"ticks": 1, "input": {"moveX": 0, "moveY": 0, "aimX": 1, "aimY": 0, "buttons": 1}},
        ],
        "totalTicks": 3,
        "provisionalResult": {
            "outcome": "success",
            "completedObjectiveIds": ["clear-frogs"],
            "objectives": [{"id": "clear-frogs", "defeated": 1, "target": 1, "completed": True}],
            "playerHealth": 8,
            "playerDefeated": False,
            "totalTicks": 3,
            "stats": {"hitsLanded": 1, "heavyHits": 0, "damageTaken": 0, "parries": 0, "dodgedAttacks": 0, "enemiesDefeated": 1},
        },
        "authority": "Arc replay required",
    }


def append_entry(spool: Path, sequence: int, kind: str, payload: dict, authority: str) -> None:
    stem = f"{sequence:08d}-{kind}"
    payload_relative = f"payloads/{stem}.payload.json"
    entry_relative = f"entries/{stem}.entry.json"
    payload_path = spool / payload_relative
    write_json(payload_path, payload)
    write_json(
        spool / entry_relative,
        {
            "format": "rodoh-action-session-spool-entry/1",
            "sessionId": "frog-pit-001",
            "sequence": sequence,
            "generatedAt": f"2026-07-26T00:00:{sequence:02d}Z",
            "kind": kind,
            "payloadFile": payload_relative,
            "payloadSha256": digest(payload_path),
            "authority": authority,
        },
    )
    write_json(
        spool / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "frog-pit-001",
            "nextSequence": sequence + 1,
            "lastEntry": entry_relative,
        },
    )


def test_ingest_is_resumable_and_idempotent(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    journal_root = tmp_path / "journal"
    append_entry(spool, 1, "physical_session_stopped", observation(), "physical safety stop only")

    first = ingest_spool(spool, journal_root)
    second = ingest_spool(spool, journal_root)
    append_entry(spool, 2, "action_candidate", candidate(), "Arc replay required")
    third = ingest_spool(spool, journal_root)

    assert first.first_sequence == 1
    assert first.last_sequence == 1
    assert first.ingested == 1
    assert second.first_sequence is None
    assert second.last_sequence == 1
    assert second.ingested == 0
    assert third.first_sequence == 2
    assert third.last_sequence == 2
    assert third.ingested == 1
    verified = ActionSessionJournal(journal_root).verify()
    assert verified.stopped_observations == 1
    assert verified.provisional_candidate_digest


def test_payload_tamper_is_refused(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    append_entry(spool, 1, "physical_session_stopped", observation(), "physical safety stop only")
    payload = next((spool / "payloads").glob("*.json"))
    value = json.loads(payload.read_text(encoding="utf-8"))
    value["reason"] = "fabricated"
    write_json(payload, value)

    with pytest.raises(ActionSessionError, match="digest mismatch"):
        ingest_spool(spool, tmp_path / "journal")


def test_payload_path_escape_is_refused(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    append_entry(spool, 1, "physical_session_stopped", observation(), "physical safety stop only")
    entry = next((spool / "entries").glob("*.json"))
    value = json.loads(entry.read_text(encoding="utf-8"))
    value["payloadFile"] = "../outside.json"
    write_json(tmp_path / "outside.json", observation())
    write_json(entry, value)

    with pytest.raises(ActionSessionError, match="escapes the spool root"):
        ingest_spool(spool, tmp_path / "journal")


def test_unknown_entry_kind_is_refused(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    append_entry(spool, 1, "campaign_mutation", {"format": "forbidden"}, "Unity authority")

    with pytest.raises(ActionSessionError, match="Unsupported action spool entry kind"):
        ingest_spool(spool, tmp_path / "journal")


def test_candidate_authority_is_checked_by_spool_and_journal(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    append_entry(spool, 1, "action_candidate", candidate(), "Unity accepted")

    with pytest.raises(ActionSessionError, match="invalid authority"):
        ingest_spool(spool, tmp_path / "journal")


def test_spool_start_cannot_change_after_initial_ingest(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    journal_root = tmp_path / "journal"
    append_entry(spool, 1, "physical_session_stopped", observation(), "physical safety stop only")
    ingest_spool(spool, journal_root)
    start = json.loads((spool / "session-start.json").read_text(encoding="utf-8"))
    start["deviceId"] = "different-device"
    write_json(spool / "session-start.json", start)

    with pytest.raises(ActionSessionError, match="start changed"):
        ingest_spool(spool, journal_root)


def test_index_rollback_is_refused(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    journal_root = tmp_path / "journal"
    append_entry(spool, 1, "physical_session_stopped", observation(), "physical safety stop only")
    ingest_spool(spool, journal_root)
    write_json(
        spool / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "frog-pit-001",
            "nextSequence": 1,
            "lastEntry": None,
        },
    )

    with pytest.raises(ActionSessionError, match="moved backward"):
        ingest_spool(spool, journal_root)


def test_existing_unbound_journal_is_not_replayed(tmp_path: Path) -> None:
    spool = create_spool(tmp_path)
    journal_root = tmp_path / "journal"
    ActionSessionJournal.create(
        journal_root,
        session_id="frog-pit-001",
        arc_digest=ARC,
        action_spec_digest=SPEC,
        device_id="quest-3-fixture",
        job_digest=JOB,
    )

    with pytest.raises(ActionSessionError, match="lacks spool-ingest"):
        ingest_spool(spool, journal_root)
