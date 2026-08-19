"""Strict duplicate-key refusing Unity and Quest action-spool ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import action_session as session
from . import action_spool as spool
from .strict_json import StrictJsonError, read_object


def _strict_session_read(path: Path) -> dict:
    try:
        return read_object(path, maximum_bytes=session.MAX_EVENT_BYTES * 8)
    except StrictJsonError as exc:
        raise session.ActionSessionError(str(exc)) from exc


def _strict_spool_read(path: Path, *, maximum: int = spool.MAX_SOURCE_BYTES) -> dict:
    try:
        return read_object(path, maximum_bytes=maximum)
    except StrictJsonError as exc:
        raise session.ActionSessionError(str(exc)) from exc


def install_strict_readers() -> None:
    session._read_json = _strict_session_read
    spool._read_object = _strict_spool_read


def main(argv: Sequence[str] | None = None) -> int:
    install_strict_readers()
    parser = argparse.ArgumentParser(description="Strictly ingest a Unity or Quest RODOH action-session spool.")
    parser.add_argument("spool")
    parser.add_argument("journal")
    args = parser.parse_args(argv)
    try:
        result = spool.ingest_spool(args.spool, args.journal)
    except session.ActionSessionError as exc:
        parser.exit(1, f"error: {exc}\n")
    print(
        json.dumps(
            {
                "format": "axm-embodied-action-spool-ingest-receipt/2",
                "status": "pass",
                "strictJson": True,
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
