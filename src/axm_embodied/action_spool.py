"""Resumable ingestion of Unity and Quest action-session spools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .action_session import (
    ActionSessionError,
    ActionSessionJournal,
    CANDIDATE_FORMAT,
    OBSERVATION_FORMAT,
)

START_FORMAT = "rodoh-action-session-spool-start/1"
INDEX_FORMAT = "rodoh-action-session-spool-index/1"
ENTRY_FORMAT = "rodoh-action-session-spool-entry/1"
INGEST_FORMAT = "axm-embodied-action-spool-ingest/1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 100_000


@dataclass(frozen=True)
class IngestResult:
    session_id: str
    first_sequence: int | None
    last_sequence: int
    ingested: int
    journal_head: str
    journal_events: int


def _read_object(path: Path, *, maximum: int = MAX_SOURCE_BYTES) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ActionSessionError(f"Unable to read spool JSON {path}: {exc}.") from exc
    if len(raw) > maximum:
        raise ActionSessionError(f"Spool JSON exceeds {maximum} bytes: {path}.")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionSessionError(f"Invalid spool JSON {path}: {exc}.") from exc
    if type(value) is not dict:
        raise ActionSessionError(f"Spool JSON root must be an object: {path}.")
    return value


def _exact(value: Mapping[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ActionSessionError(f"{label} contains unknown field(s): {', '.join(sorted(unknown))}.")
    if missing:
        raise ActionSessionError(f"{label} is missing field(s): {', '.join(sorted(missing))}.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _source_path(spool: Path, relative_path: Any, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ActionSessionError(f"{label} must be a non-empty normalized relative path.")
    candidate = (spool / relative_path).resolve()
    if not _inside(spool, candidate):
        raise ActionSessionError(f"{label} escapes the spool root: {relative_path}.")
    if not candidate.is_file():
        raise ActionSessionError(f"{label} is absent: {relative_path}.")
    return candidate


def _validate_start(start: Mapping[str, Any]) -> None:
    fields = {
        "format",
        "generatedAt",
        "sessionId",
        "deviceId",
        "arcDigest",
        "actionSpecDigest",
        "unityJobDigest",
        "unityVersion",
        "platform",
        "authority",
    }
    _exact(start, fields, fields, "action spool start")
    if start["format"] != START_FORMAT:
        raise ActionSessionError("Unsupported action spool start format.")
    if start["authority"] != "physical and provisional Unity source only":
        raise ActionSessionError("Action spool start falsely claims accepted authority.")
    for field in ("sessionId", "deviceId", "arcDigest", "actionSpecDigest", "unityVersion", "platform"):
        if not isinstance(start[field], str) or not start[field]:
            raise ActionSessionError(f"Action spool start {field} must be a non-empty string.")
    job_digest = start["unityJobDigest"]
    if job_digest is not None and (not isinstance(job_digest, str) or not re.fullmatch(r"unityjob1_[0-9a-f]{64}", job_digest)):
        raise ActionSessionError("Action spool unityJobDigest is malformed.")


def _validate_index(index: Mapping[str, Any], session_id: str) -> None:
    fields = {"format", "sessionId", "nextSequence", "lastEntry"}
    _exact(index, fields, fields, "action spool index")
    if index["format"] != INDEX_FORMAT or index["sessionId"] != session_id:
        raise ActionSessionError("Action spool index format or session identity is invalid.")
    next_sequence = index["nextSequence"]
    if not isinstance(next_sequence, int) or isinstance(next_sequence, bool) or next_sequence < 1 or next_sequence > MAX_ENTRIES + 1:
        raise ActionSessionError("Action spool nextSequence is outside the supported range.")
    if index["lastEntry"] is not None and not isinstance(index["lastEntry"], str):
        raise ActionSessionError("Action spool lastEntry must be a string or null.")


def _validate_entry(entry: Mapping[str, Any], session_id: str, sequence: int) -> None:
    fields = {"format", "sessionId", "sequence", "generatedAt", "kind", "payloadFile", "payloadSha256", "authority"}
    _exact(entry, fields, fields, f"action spool entry {sequence}")
    if entry["format"] != ENTRY_FORMAT or entry["sessionId"] != session_id:
        raise ActionSessionError(f"Action spool entry {sequence} format or session identity is invalid.")
    if entry["sequence"] != sequence:
        raise ActionSessionError(f"Action spool entry {sequence} has a non-contiguous sequence.")
    if not isinstance(entry["kind"], str) or not entry["kind"]:
        raise ActionSessionError(f"Action spool entry {sequence} kind is absent.")
    if not isinstance(entry["authority"], str) or not entry["authority"]:
        raise ActionSessionError(f"Action spool entry {sequence} authority is absent.")
    if not isinstance(entry["payloadSha256"], str) or not SHA256_RE.fullmatch(entry["payloadSha256"]):
        raise ActionSessionError(f"Action spool entry {sequence} payload digest is malformed.")


def _load_or_create_journal(spool: Path, journal_root: Path, start: Mapping[str, Any]) -> tuple[ActionSessionJournal, dict[str, Any]]:
    state_path = journal_root / "spool-ingest.json"
    if not journal_root.exists():
        journal = ActionSessionJournal.create(
            journal_root,
            session_id=start["sessionId"],
            arc_digest=start["arcDigest"],
            action_spec_digest=start["actionSpecDigest"],
            device_id=start["deviceId"],
            job_digest=start["unityJobDigest"],
            generated_at=start["generatedAt"],
        )
        state = {
            "format": INGEST_FORMAT,
            "sessionId": start["sessionId"],
            "spoolRoot": str(spool),
            "spoolStartSha256": _sha256(spool / "session-start.json"),
            "lastSequence": 0,
            "lastEntrySha256": None,
        }
        _atomic_json(state_path, state)
        return journal, state
    if not state_path.is_file():
        raise ActionSessionError("Existing action-session journal lacks spool-ingest.json; refusing an ambiguous replay.")
    journal = ActionSessionJournal(journal_root)
    journal.verify()
    state = _read_object(state_path)
    fields = {"format", "sessionId", "spoolRoot", "spoolStartSha256", "lastSequence", "lastEntrySha256"}
    _exact(state, fields, fields, "action spool ingest state")
    if state["format"] != INGEST_FORMAT or state["sessionId"] != start["sessionId"]:
        raise ActionSessionError("Action spool ingest state format or session identity is invalid.")
    if state["spoolRoot"] != str(spool):
        raise ActionSessionError("Action-session journal is bound to a different spool root.")
    if state["spoolStartSha256"] != _sha256(spool / "session-start.json"):
        raise ActionSessionError("Action spool start changed after journal creation.")
    if not isinstance(state["lastSequence"], int) or isinstance(state["lastSequence"], bool) or state["lastSequence"] < 0:
        raise ActionSessionError("Action spool ingest lastSequence is invalid.")
    return journal, state


def ingest_spool(spool_root: Path | str, journal_root: Path | str) -> IngestResult:
    spool = Path(spool_root).resolve()
    journal_path = Path(journal_root).resolve()
    if not spool.is_dir():
        raise ActionSessionError(f"Action spool directory is absent: {spool}.")
    start_path = spool / "session-start.json"
    index_path = spool / "index.json"
    start = _read_object(start_path)
    _validate_start(start)
    index = _read_object(index_path)
    _validate_index(index, start["sessionId"])
    journal, state = _load_or_create_journal(spool, journal_path, start)
    last_sequence = state["lastSequence"]
    highest_available = index["nextSequence"] - 1
    if highest_available < last_sequence:
        raise ActionSessionError("Action spool index moved backward after ingestion.")
    first_ingested: int | None = None
    ingested = 0

    for sequence in range(last_sequence + 1, highest_available + 1):
        prefix = f"{sequence:08d}-"
        matching = sorted((spool / "entries").glob(prefix + "*.entry.json"))
        if len(matching) != 1:
            raise ActionSessionError(f"Action spool sequence {sequence} has {len(matching)} entry files; expected exactly one.")
        entry_path = matching[0].resolve()
        if not _inside(spool, entry_path):
            raise ActionSessionError(f"Action spool entry {sequence} escapes the spool root.")
        entry = _read_object(entry_path)
        _validate_entry(entry, start["sessionId"], sequence)
        payload_path = _source_path(spool, entry["payloadFile"], f"action spool payload {sequence}")
        payload_digest = _sha256(payload_path)
        if payload_digest != entry["payloadSha256"]:
            raise ActionSessionError(f"Action spool payload {sequence} digest mismatch.")
        payload = _read_object(payload_path)

        if entry["kind"] == "physical_session_stopped":
            if entry["authority"] != "physical safety stop only" or payload.get("format") != OBSERVATION_FORMAT:
                raise ActionSessionError(f"Action spool physical observation {sequence} has invalid authority or format.")
            journal.append_observation(payload, source_path=str(payload_path))
        elif entry["kind"] == "action_candidate":
            if entry["authority"] != "Arc replay required" or payload.get("format") != CANDIDATE_FORMAT:
                raise ActionSessionError(f"Action spool candidate {sequence} has invalid authority or format.")
            journal.attach_candidate(payload, source_path=str(payload_path))
        else:
            raise ActionSessionError(f"Unsupported action spool entry kind at sequence {sequence}: {entry['kind']}.")

        state["lastSequence"] = sequence
        state["lastEntrySha256"] = _sha256(entry_path)
        _atomic_json(journal_path / "spool-ingest.json", state)
        if first_ingested is None:
            first_ingested = sequence
        ingested += 1

    if highest_available > 0:
        expected_last = index["lastEntry"]
        if not isinstance(expected_last, str):
            raise ActionSessionError("Action spool index has entries but no lastEntry path.")
        last_entry_path = _source_path(spool, expected_last, "action spool lastEntry")
        if state["lastEntrySha256"] != _sha256(last_entry_path):
            raise ActionSessionError("Action spool ingest state does not match the indexed final entry.")
    verified = journal.verify()
    return IngestResult(
        session_id=start["sessionId"],
        first_sequence=first_ingested,
        last_sequence=state["lastSequence"],
        ingested=ingested,
        journal_head=verified.head_digest,
        journal_events=verified.event_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest a Unity or Quest RODOH action-session spool.")
    parser.add_argument("spool")
    parser.add_argument("journal")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = ingest_spool(args.spool, args.journal)
    except ActionSessionError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(
        json.dumps(
            {
                "format": "axm-embodied-action-spool-ingest-receipt/1",
                "status": "pass",
                "sessionId": result.session_id,
                "firstSequence": result.first_sequence,
                "lastSequence": result.last_sequence,
                "ingested": result.ingested,
                "journalHead": result.journal_head,
                "journalEvents": result.journal_events,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
