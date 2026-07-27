"""Tamper-evident physical-session custody for RODOH action encounters.

This module links Unity tracking and guardian observations, a provisional action
execution candidate, and the later Arc-owned action receipt without granting any
of those records authority they do not possess.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

SESSION_FORMAT = "axm-embodied-action-session/1"
EVENT_FORMAT = "axm-embodied-action-session-event/1"
MANIFEST_FORMAT = "axm-embodied-action-session-manifest/1"
OBSERVATION_FORMAT = "rodoh-embodied-action-observation/1"
CANDIDATE_FORMAT = "rodoh-action-execution-candidate/1"
RECEIPT_FORMAT = "axm-action-receipt/1"
GENESIS_SHARD_FORMAT = "axm-genesis-shard/1"
ZERO_DIGEST = "0" * 64
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PREFIXED_DIGEST_RE = re.compile(r"^(?:cart1_|actspec1_|acttrace1_|actreceipt1_|unityjob1_)[0-9a-f]{64}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_EVENT_BYTES = 256 * 1024
MAX_EVENTS = 100_000
MAX_STRING = 16_384
MAX_DEPTH = 16
MAX_CONTAINER_ITEMS = 4_096


class ActionSessionError(ValueError):
    """Raised when an action-session record violates custody or authority law."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    _validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ActionSessionError("JSON value exceeds the action-session depth limit.")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ActionSessionError("JSON number must be finite.")
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING:
            raise ActionSessionError("JSON string exceeds the action-session byte limit.")
        return
    if isinstance(value, list):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ActionSessionError("JSON array exceeds the action-session item limit.")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if type(value) is not dict:
            raise ActionSessionError("JSON objects must use the built-in dict type.")
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ActionSessionError("JSON object exceeds the action-session member limit.")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ActionSessionError("JSON object keys must be strings.")
            _validate_json_value(key, depth=depth + 1)
            _validate_json_value(item, depth=depth + 1)
        return
    raise ActionSessionError(f"Unsupported JSON value type: {type(value).__name__}.")


def _require_exact_keys(value: Mapping[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ActionSessionError(f"{label} contains unknown field(s): {', '.join(sorted(unknown))}.")
    if missing:
        raise ActionSessionError(f"{label} is missing field(s): {', '.join(sorted(missing))}.")


def _require_text(value: Any, label: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value:
        raise ActionSessionError(f"{label} must be a non-empty string.")
    if len(value.encode("utf-8")) > maximum:
        raise ActionSessionError(f"{label} exceeds {maximum} UTF-8 bytes.")
    return value


def _require_prefixed_digest(value: Any, prefix: str, label: str) -> str:
    text = _require_text(value, label, maximum=128)
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", text):
        raise ActionSessionError(f"{label} must be {prefix}<64 lowercase hexadecimal characters>.")
    return text


def _require_plain_digest(value: Any, label: str) -> str:
    text = _require_text(value, label, maximum=64)
    if not DIGEST_RE.fullmatch(text):
        raise ActionSessionError(f"{label} must be 64 lowercase hexadecimal characters.")
    return text


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_EVENT_BYTES * 8:
        raise ActionSessionError(f"JSON source is too large: {path}.")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionSessionError(f"Invalid JSON in {path}: {exc}.") from exc
    if type(value) is not dict:
        raise ActionSessionError(f"JSON root must be an object: {path}.")
    _validate_json_value(value)
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class VerifiedJournal:
    event_count: int
    head_digest: str
    accepted_receipt_digest: str | None
    provisional_candidate_digest: str | None
    stopped_observations: int


class ActionSessionJournal:
    """Append-only, hash-chained custody for one physical action session."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.events_path = self.root / "events.jsonl"
        self.manifest_path = self.root / "manifest.json"

    @classmethod
    def create(
        cls,
        root: Path | str,
        *,
        session_id: str,
        arc_digest: str,
        action_spec_digest: str,
        device_id: str,
        job_digest: str | None = None,
        generated_at: str | None = None,
    ) -> "ActionSessionJournal":
        journal = cls(root)
        if journal.root.exists() and any(journal.root.iterdir()):
            raise ActionSessionError(f"Action-session directory is not empty: {journal.root}.")
        if not SESSION_ID_RE.fullmatch(session_id):
            raise ActionSessionError("session_id contains unsupported characters or exceeds 128 characters.")
        arc_digest = _require_prefixed_digest(arc_digest, "cart1_", "arc_digest")
        action_spec_digest = _require_prefixed_digest(action_spec_digest, "actspec1_", "action_spec_digest")
        device_id = _require_text(device_id, "device_id", maximum=256)
        if job_digest is not None:
            job_digest = _require_prefixed_digest(job_digest, "unityjob1_", "job_digest")
        created = generated_at or _utc_now()
        manifest = {
            "format": MANIFEST_FORMAT,
            "sessionFormat": SESSION_FORMAT,
            "sessionId": session_id,
            "createdAt": created,
            "arcDigest": arc_digest,
            "actionSpecDigest": action_spec_digest,
            "deviceId": device_id,
            "jobDigest": job_digest,
            "events": "events.jsonl",
            "eventCount": 0,
            "headDigest": ZERO_DIGEST,
            "candidateDigest": None,
            "acceptedReceiptDigest": None,
            "authority": {
                "action": "Arc axm-action-receipt/1 only",
                "physical": "axm-embodied observation and capture evidence",
                "presentation": "Unity local session",
            },
        }
        journal.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(journal.events_path, b"")
        _atomic_write(journal.manifest_path, _canonical_bytes(manifest) + b"\n")
        journal.append_event(
            "session_started",
            {
                "sessionId": session_id,
                "arcDigest": arc_digest,
                "actionSpecDigest": action_spec_digest,
                "deviceId": device_id,
                "jobDigest": job_digest,
            },
            recorded_at=created,
        )
        return journal

    def _manifest(self) -> dict[str, Any]:
        manifest = _read_json(self.manifest_path)
        _require_exact_keys(
            manifest,
            {
                "format",
                "sessionFormat",
                "sessionId",
                "createdAt",
                "arcDigest",
                "actionSpecDigest",
                "deviceId",
                "jobDigest",
                "events",
                "eventCount",
                "headDigest",
                "candidateDigest",
                "acceptedReceiptDigest",
                "authority",
            },
            {
                "format",
                "sessionFormat",
                "sessionId",
                "createdAt",
                "arcDigest",
                "actionSpecDigest",
                "deviceId",
                "jobDigest",
                "events",
                "eventCount",
                "headDigest",
                "candidateDigest",
                "acceptedReceiptDigest",
                "authority",
            },
            "action-session manifest",
        )
        if manifest["format"] != MANIFEST_FORMAT or manifest["sessionFormat"] != SESSION_FORMAT:
            raise ActionSessionError("Action-session manifest format is unsupported.")
        if manifest["events"] != "events.jsonl":
            raise ActionSessionError("Action-session event path is not canonical.")
        _require_plain_digest(manifest["headDigest"], "manifest.headDigest")
        return manifest

    def append_event(self, kind: str, payload: Mapping[str, Any], *, recorded_at: str | None = None) -> dict[str, Any]:
        kind = _require_text(kind, "event kind", maximum=128)
        if type(payload) is not dict:
            payload = dict(payload)
        _validate_json_value(payload)
        manifest = self._manifest()
        sequence = int(manifest["eventCount"]) + 1
        if sequence > MAX_EVENTS:
            raise ActionSessionError("Action-session event limit has been reached.")
        previous = _require_plain_digest(manifest["headDigest"], "manifest.headDigest")
        event_without_digest = {
            "format": EVENT_FORMAT,
            "sessionId": manifest["sessionId"],
            "sequence": sequence,
            "recordedAt": recorded_at or _utc_now(),
            "kind": kind,
            "payload": payload,
            "previousDigest": previous,
        }
        digest = _sha256(previous.encode("ascii") + b"\n" + _canonical_bytes(event_without_digest))
        event = {**event_without_digest, "eventDigest": digest}
        encoded = _canonical_bytes(event) + b"\n"
        if len(encoded) > MAX_EVENT_BYTES:
            raise ActionSessionError("Action-session event exceeds the event byte limit.")
        with self.events_path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        manifest["eventCount"] = sequence
        manifest["headDigest"] = digest
        _atomic_write(self.manifest_path, _canonical_bytes(manifest) + b"\n")
        return event

    def append_observation(self, observation: Mapping[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
        value = dict(observation)
        _require_exact_keys(
            value,
            {
                "format",
                "generatedAt",
                "reason",
                "actionSpecDigest",
                "actionTick",
                "headX",
                "headY",
                "headZ",
                "displacementMeters",
                "boundaryClearanceMeters",
                "boundaryKnown",
                "applicationFocused",
                "actionOutcome",
                "authority",
            },
            {
                "format",
                "generatedAt",
                "reason",
                "actionSpecDigest",
                "actionTick",
                "headX",
                "headY",
                "headZ",
                "displacementMeters",
                "boundaryClearanceMeters",
                "boundaryKnown",
                "applicationFocused",
                "actionOutcome",
                "authority",
            },
            "embodied action observation",
        )
        if value["format"] != OBSERVATION_FORMAT:
            raise ActionSessionError("Unsupported embodied action observation format.")
        manifest = self._manifest()
        if value["actionSpecDigest"] != manifest["actionSpecDigest"]:
            raise ActionSessionError("Embodied observation is bound to a different action spec.")
        if value["actionOutcome"] != "uncommitted":
            raise ActionSessionError("Physical observations may not claim a committed action outcome.")
        if value["authority"] != "physical safety stop only":
            raise ActionSessionError("Physical observation authority statement is missing or altered.")
        tick = value["actionTick"]
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            raise ActionSessionError("Embodied observation actionTick must be a non-negative integer.")
        for field in ("headX", "headY", "headZ", "displacementMeters", "boundaryClearanceMeters"):
            number = value[field]
            if not isinstance(number, (int, float)) or isinstance(number, bool) or not math.isfinite(number):
                raise ActionSessionError(f"Embodied observation {field} must be finite.")
        payload = {
            "observation": value,
            "sourcePath": source_path,
            "sourceSha256": _sha256(_canonical_bytes(value)),
            "campaignEffect": None,
        }
        return self.append_event("physical_session_stopped", payload, recorded_at=value["generatedAt"])

    def attach_candidate(self, candidate: Mapping[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
        value = dict(candidate)
        required = {
            "format",
            "sourceReceiptFormat",
            "runtimeVersion",
            "arcDigest",
            "challengeId",
            "difficultyModeId",
            "actionSpecDigest",
            "cycle",
            "seed",
            "controlledAgentId",
            "partyAgentIds",
            "trace",
            "totalTicks",
            "provisionalResult",
            "authority",
        }
        _require_exact_keys(value, required, required, "Unity action execution candidate")
        if value["format"] != CANDIDATE_FORMAT or value["sourceReceiptFormat"] != RECEIPT_FORMAT:
            raise ActionSessionError("Unsupported Unity action execution candidate format.")
        if value["authority"] != "Arc replay required":
            raise ActionSessionError("Unity action candidate falsely claims accepted authority.")
        manifest = self._manifest()
        if manifest["candidateDigest"] is not None:
            raise ActionSessionError("Action-session journal already contains a provisional candidate.")
        if value["arcDigest"] != manifest["arcDigest"] or value["actionSpecDigest"] != manifest["actionSpecDigest"]:
            raise ActionSessionError("Unity action candidate identity differs from the physical session.")
        total_ticks = value["totalTicks"]
        if not isinstance(total_ticks, int) or isinstance(total_ticks, bool) or total_ticks < 0:
            raise ActionSessionError("Unity candidate totalTicks must be a non-negative integer.")
        trace = value["trace"]
        if not isinstance(trace, list) or len(trace) > MAX_CONTAINER_ITEMS:
            raise ActionSessionError("Unity candidate trace must be a bounded run array.")
        expanded = 0
        for index, run in enumerate(trace):
            if type(run) is not dict or set(run) != {"ticks", "input"}:
                raise ActionSessionError(f"Unity candidate trace run {index} is malformed.")
            ticks = run["ticks"]
            if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks <= 0:
                raise ActionSessionError(f"Unity candidate trace run {index} has an invalid tick count.")
            expanded += ticks
            input_frame = run["input"]
            if type(input_frame) is not dict or set(input_frame) != {"moveX", "moveY", "aimX", "aimY", "buttons"}:
                raise ActionSessionError(f"Unity candidate trace input {index} is malformed.")
            for axis in ("moveX", "moveY", "aimX", "aimY"):
                if input_frame[axis] not in (-1, 0, 1):
                    raise ActionSessionError(f"Unity candidate trace input {index}.{axis} is outside the signed axis law.")
            buttons = input_frame["buttons"]
            if not isinstance(buttons, int) or isinstance(buttons, bool) or buttons < 0 or buttons > 15:
                raise ActionSessionError(f"Unity candidate trace input {index}.buttons is outside the v1 mask.")
        if expanded != total_ticks:
            raise ActionSessionError("Unity candidate compressed trace does not cover totalTicks exactly.")
        digest = _sha256(_canonical_bytes(value))
        event = self.append_event(
            "action_candidate_attached",
            {
                "candidateFormat": CANDIDATE_FORMAT,
                "candidateSha256": digest,
                "sourcePath": source_path,
                "totalTicks": total_ticks,
                "provisionalOutcome": value["provisionalResult"].get("outcome") if isinstance(value["provisionalResult"], dict) else None,
                "acceptedOutcome": None,
                "authority": "Arc replay required",
            },
        )
        manifest = self._manifest()
        manifest["candidateDigest"] = digest
        _atomic_write(self.manifest_path, _canonical_bytes(manifest) + b"\n")
        return event

    def attach_receipt(self, receipt: Mapping[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
        value = dict(receipt)
        if value.get("format") != RECEIPT_FORMAT:
            raise ActionSessionError("Unsupported accepted action receipt format.")
        manifest = self._manifest()
        if manifest["acceptedReceiptDigest"] is not None:
            raise ActionSessionError("Action-session journal already contains an accepted action receipt.")
        if manifest["candidateDigest"] is None:
            raise ActionSessionError("Accepted action receipt cannot precede the provisional execution candidate.")
        if value.get("arcDigest") != manifest["arcDigest"] or value.get("actionSpecDigest") != manifest["actionSpecDigest"]:
            raise ActionSessionError("Accepted action receipt identity differs from the physical session.")
        receipt_digest = value.get("receiptDigest")
        if receipt_digest is not None:
            _require_prefixed_digest(receipt_digest, "actreceipt1_", "receipt.receiptDigest")
        canonical_digest = _sha256(_canonical_bytes(value))
        outcome = value.get("result", {}).get("outcome") if isinstance(value.get("result"), dict) else value.get("outcome")
        if outcome not in {"success", "partial", "failure"}:
            raise ActionSessionError("Accepted action receipt does not expose a valid terminal outcome.")
        event = self.append_event(
            "arc_receipt_attached",
            {
                "receiptFormat": RECEIPT_FORMAT,
                "receiptSha256": canonical_digest,
                "sourcePath": source_path,
                "acceptedOutcome": outcome,
                "authority": "Arc replay verified",
            },
        )
        manifest = self._manifest()
        manifest["acceptedReceiptDigest"] = canonical_digest
        _atomic_write(self.manifest_path, _canonical_bytes(manifest) + b"\n")
        return event

    def append_capture(
        self,
        *,
        stream: str,
        path: str,
        sha256: str,
        media_type: str,
        byte_length: int,
        action_tick: int | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        stream = _require_text(stream, "capture stream", maximum=128)
        path = _require_text(path, "capture path", maximum=2048)
        sha256 = _require_plain_digest(sha256, "capture sha256")
        media_type = _require_text(media_type, "capture media_type", maximum=256)
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
            raise ActionSessionError("capture byte_length must be a non-negative integer.")
        if action_tick is not None and (not isinstance(action_tick, int) or isinstance(action_tick, bool) or action_tick < 0):
            raise ActionSessionError("capture action_tick must be a non-negative integer or null.")
        return self.append_event(
            "capture_recorded",
            {
                "stream": stream,
                "path": path,
                "sha256": sha256,
                "mediaType": media_type,
                "byteLength": byte_length,
                "actionTick": action_tick,
                "semanticAuthority": None,
            },
            recorded_at=timestamp,
        )

    def verify(self) -> VerifiedJournal:
        manifest = self._manifest()
        previous = ZERO_DIGEST
        count = 0
        accepted: str | None = None
        candidate: str | None = None
        stopped = 0
        with self.events_path.open("rb") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    raise ActionSessionError("Action-session journal contains an empty event line.")
                if len(raw_line) > MAX_EVENT_BYTES:
                    raise ActionSessionError("Action-session journal contains an oversized event line.")
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ActionSessionError(f"Invalid action-session event JSON at line {count + 1}: {exc}.") from exc
                if type(event) is not dict:
                    raise ActionSessionError(f"Action-session event line {count + 1} is not an object.")
                _require_exact_keys(
                    event,
                    {"format", "sessionId", "sequence", "recordedAt", "kind", "payload", "previousDigest", "eventDigest"},
                    {"format", "sessionId", "sequence", "recordedAt", "kind", "payload", "previousDigest", "eventDigest"},
                    f"action-session event line {count + 1}",
                )
                count += 1
                if event["format"] != EVENT_FORMAT or event["sessionId"] != manifest["sessionId"]:
                    raise ActionSessionError(f"Action-session event line {count} has the wrong format or session identity.")
                if event["sequence"] != count:
                    raise ActionSessionError(f"Action-session event line {count} has a non-contiguous sequence.")
                if event["previousDigest"] != previous:
                    raise ActionSessionError(f"Action-session event line {count} breaks the previous-digest chain.")
                without_digest = {key: event[key] for key in event if key != "eventDigest"}
                expected = _sha256(previous.encode("ascii") + b"\n" + _canonical_bytes(without_digest))
                if event["eventDigest"] != expected:
                    raise ActionSessionError(f"Action-session event line {count} has an invalid digest.")
                previous = expected
                if event["kind"] == "action_candidate_attached":
                    candidate = event["payload"].get("candidateSha256")
                elif event["kind"] == "arc_receipt_attached":
                    accepted = event["payload"].get("receiptSha256")
                elif event["kind"] == "physical_session_stopped":
                    stopped += 1
                    if event["payload"].get("campaignEffect") is not None:
                        raise ActionSessionError("Physical stop event contains an unauthorized campaign effect.")
        if count != manifest["eventCount"] or previous != manifest["headDigest"]:
            raise ActionSessionError("Action-session manifest does not match the event journal head.")
        if candidate != manifest["candidateDigest"] or accepted != manifest["acceptedReceiptDigest"]:
            raise ActionSessionError("Action-session manifest attachment digests differ from the journal.")
        return VerifiedJournal(count, previous, accepted, candidate, stopped)

    def to_genesis_shard(self) -> dict[str, Any]:
        verified = self.verify()
        manifest = self._manifest()
        return {
            "format": GENESIS_SHARD_FORMAT,
            "sourceFormat": SESSION_FORMAT,
            "sourceId": manifest["sessionId"],
            "sourceDigest": verified.head_digest,
            "sourceEventCount": verified.event_count,
            "claims": {
                "arcDigest": manifest["arcDigest"],
                "actionSpecDigest": manifest["actionSpecDigest"],
                "candidateSha256": verified.provisional_candidate_digest,
                "acceptedReceiptSha256": verified.accepted_receipt_digest,
                "physicalStopCount": verified.stopped_observations,
            },
            "authority": {
                "physicalEvidence": True,
                "actionOutcome": verified.accepted_receipt_digest is not None,
                "actionOutcomeAuthority": "attached Arc receipt" if verified.accepted_receipt_digest else None,
                "campaignMutation": False,
            },
        }


def _command_init(args: argparse.Namespace) -> int:
    ActionSessionJournal.create(
        args.root,
        session_id=args.session_id,
        arc_digest=args.arc_digest,
        action_spec_digest=args.action_spec_digest,
        device_id=args.device_id,
        job_digest=args.job_digest,
    ).verify()
    return 0


def _command_append_observation(args: argparse.Namespace) -> int:
    journal = ActionSessionJournal(args.root)
    journal.append_observation(_read_json(Path(args.observation)), source_path=args.observation)
    journal.verify()
    return 0


def _command_attach_candidate(args: argparse.Namespace) -> int:
    journal = ActionSessionJournal(args.root)
    journal.attach_candidate(_read_json(Path(args.candidate)), source_path=args.candidate)
    journal.verify()
    return 0


def _command_attach_receipt(args: argparse.Namespace) -> int:
    journal = ActionSessionJournal(args.root)
    journal.attach_receipt(_read_json(Path(args.receipt)), source_path=args.receipt)
    journal.verify()
    return 0


def _command_verify(args: argparse.Namespace) -> int:
    verified = ActionSessionJournal(args.root).verify()
    print(json.dumps({"format": "axm-embodied-action-session-verification/1", "status": "pass", **verified.__dict__}, indent=2, sort_keys=True))
    return 0


def _command_shard(args: argparse.Namespace) -> int:
    shard = ActionSessionJournal(args.root).to_genesis_shard()
    output = _canonical_bytes(shard) + b"\n"
    if args.output:
        _atomic_write(Path(args.output), output)
    else:
        print(output.decode("utf-8"), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and verify RODOH embodied action sessions.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    initialize = subcommands.add_parser("init")
    initialize.add_argument("root")
    initialize.add_argument("--session-id", required=True)
    initialize.add_argument("--arc-digest", required=True)
    initialize.add_argument("--action-spec-digest", required=True)
    initialize.add_argument("--device-id", required=True)
    initialize.add_argument("--job-digest")
    initialize.set_defaults(function=_command_init)

    observation = subcommands.add_parser("append-observation")
    observation.add_argument("root")
    observation.add_argument("observation")
    observation.set_defaults(function=_command_append_observation)

    candidate = subcommands.add_parser("attach-candidate")
    candidate.add_argument("root")
    candidate.add_argument("candidate")
    candidate.set_defaults(function=_command_attach_candidate)

    receipt = subcommands.add_parser("attach-receipt")
    receipt.add_argument("root")
    receipt.add_argument("receipt")
    receipt.set_defaults(function=_command_attach_receipt)

    verify = subcommands.add_parser("verify")
    verify.add_argument("root")
    verify.set_defaults(function=_command_verify)

    shard = subcommands.add_parser("shard")
    shard.add_argument("root")
    shard.add_argument("--output")
    shard.set_defaults(function=_command_shard)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.function(args))
    except ActionSessionError as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
