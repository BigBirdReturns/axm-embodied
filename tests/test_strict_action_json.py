from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from axm_embodied import action_session, action_spool
from axm_embodied.action_session import ActionSessionError, ActionSessionJournal
from axm_embodied.action_session_strict import install_strict_reader
from axm_embodied.action_spool_strict import install_strict_readers
from axm_embodied.strict_json import StrictJsonError, loads_object

ARC = "cart1_" + "a" * 64
SPEC = "actspec1_" + "b" * 64
JOB = "unityjob1_" + "c" * 64


def journal(tmp_path: Path) -> ActionSessionJournal:
    return ActionSessionJournal.create(
        tmp_path / "journal",
        session_id="strict-action-001",
        arc_digest=ARC,
        action_spec_digest=SPEC,
        device_id="quest-strict-fixture",
        job_digest=JOB,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: dict) -> None:
    write(path, json.dumps(value, separators=(",", ":")) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spool_root(tmp_path: Path) -> Path:
    root = tmp_path / "spool"
    write_json(
        root / "session-start.json",
        {
            "format": "rodoh-action-session-spool-start/1",
            "generatedAt": "2026-07-26T00:00:00Z",
            "sessionId": "strict-action-001",
            "deviceId": "quest-strict-fixture",
            "arcDigest": ARC,
            "actionSpecDigest": SPEC,
            "unityJobDigest": JOB,
            "unityVersion": "6000.0.66f2",
            "platform": "Android",
            "authority": "physical and provisional Unity source only",
        },
    )
    write_json(
        root / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "strict-action-001",
            "nextSequence": 1,
            "lastEntry": None,
        },
    )
    return root


def candidate_json_with_duplicate_authority() -> str:
    return (
        "{"
        '"format":"rodoh-action-execution-candidate/1",'
        '"sourceReceiptFormat":"axm-action-receipt/1",'
        '"runtimeVersion":"1.0.0",'
        f'"arcDigest":"{ARC}",'
        '"challengeId":"strict-fight",'
        '"difficultyModeId":null,'
        f'"actionSpecDigest":"{SPEC}",'
        '"cycle":1,'
        '"seed":7,'
        '"controlledAgentId":"agent-a",'
        '"partyAgentIds":["agent-a"],'
        '"trace":[{"ticks":1,"input":{"moveX":0,"moveY":0,"aimX":1,"aimY":0,"buttons":1}}],'
        '"totalTicks":1,'
        '"provisionalResult":{"outcome":"success"},'
        '"authority":"Unity accepted",'
        '"authority":"Arc replay required"'
        "}"
    )


def test_strict_parser_refuses_duplicate_object_keys() -> None:
    with pytest.raises(StrictJsonError, match="Duplicate JSON object key: authority"):
        loads_object(candidate_json_with_duplicate_authority())


def test_strict_session_verification_refuses_duplicate_manifest_keys(tmp_path: Path) -> None:
    value = journal(tmp_path)
    original = value.manifest_path.read_text(encoding="utf-8").strip()
    tampered = original[:-1] + ',"headDigest":"' + "0" * 64 + '"}'
    write(value.manifest_path, tampered + "\n")
    install_strict_reader()

    with pytest.raises(ActionSessionError, match="Duplicate JSON object key: headDigest"):
        value.verify()


def test_strict_session_cli_reader_refuses_duplicate_candidate_authority(tmp_path: Path) -> None:
    value = journal(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    write(candidate_path, candidate_json_with_duplicate_authority())
    install_strict_reader()

    with pytest.raises(ActionSessionError, match="Duplicate JSON object key: authority"):
        action_session._read_json(candidate_path)


def test_strict_spool_refuses_duplicate_entry_kind(tmp_path: Path) -> None:
    root = spool_root(tmp_path)
    payload = root / "payloads" / "00000001-action_candidate.payload.json"
    write(payload, candidate_json_with_duplicate_authority().replace('"authority":"Unity accepted",', ""))
    entry = root / "entries" / "00000001-action_candidate.entry.json"
    write(
        entry,
        "{"
        '"format":"rodoh-action-session-spool-entry/1",'
        '"sessionId":"strict-action-001",'
        '"sequence":1,'
        '"generatedAt":"2026-07-26T00:00:01Z",'
        '"kind":"physical_session_stopped",'
        '"kind":"action_candidate",'
        '"payloadFile":"payloads/00000001-action_candidate.payload.json",'
        f'"payloadSha256":"{sha256(payload)}",'
        '"authority":"Arc replay required"'
        "}\n",
    )
    write_json(
        root / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "strict-action-001",
            "nextSequence": 2,
            "lastEntry": "entries/00000001-action_candidate.entry.json",
        },
    )
    install_strict_readers()

    with pytest.raises(ActionSessionError, match="Duplicate JSON object key: kind"):
        action_spool.ingest_spool(root, tmp_path / "ingested")


def test_strict_spool_refuses_duplicate_payload_authority_before_semantics(tmp_path: Path) -> None:
    root = spool_root(tmp_path)
    payload = root / "payloads" / "00000001-action_candidate.payload.json"
    write(payload, candidate_json_with_duplicate_authority())
    entry = root / "entries" / "00000001-action_candidate.entry.json"
    write_json(
        entry,
        {
            "format": "rodoh-action-session-spool-entry/1",
            "sessionId": "strict-action-001",
            "sequence": 1,
            "generatedAt": "2026-07-26T00:00:01Z",
            "kind": "action_candidate",
            "payloadFile": "payloads/00000001-action_candidate.payload.json",
            "payloadSha256": sha256(payload),
            "authority": "Arc replay required",
        },
    )
    write_json(
        root / "index.json",
        {
            "format": "rodoh-action-session-spool-index/1",
            "sessionId": "strict-action-001",
            "nextSequence": 2,
            "lastEntry": "entries/00000001-action_candidate.entry.json",
        },
    )
    install_strict_readers()

    with pytest.raises(ActionSessionError, match="Duplicate JSON object key: authority"):
        action_spool.ingest_spool(root, tmp_path / "ingested")
