"""Strict duplicate-key refusing reader for embodied action-session journals."""

from __future__ import annotations

from pathlib import Path

from . import action_session as session
from .strict_json import StrictJsonError, read_object


def _strict_session_read(path: Path) -> dict:
    try:
        return read_object(path, maximum_bytes=session.MAX_EVENT_BYTES * 8)
    except StrictJsonError as exc:
        raise session.ActionSessionError(str(exc)) from exc


def install_strict_reader() -> None:
    """Install the strict reader at the session module's single JSON seam."""

    session._read_json = _strict_session_read
