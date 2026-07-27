"""Resource-bounded JSON parsing with duplicate-key refusal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 16
MAX_CONTAINER_ITEMS = 4_096
MAX_STRING_BYTES = 16_384


class StrictJsonError(ValueError):
    """Raised when JSON is malformed, ambiguous, or outside resource bounds."""


def _object_without_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError(f"Duplicate JSON object key: {key}.")
        result[key] = value
    return result


def _validate(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise StrictJsonError("JSON value exceeds the depth limit.")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise StrictJsonError("JSON numbers must be finite.")
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise StrictJsonError("JSON string exceeds the UTF-8 byte limit.")
        return
    if isinstance(value, list):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise StrictJsonError("JSON array exceeds the item limit.")
        for item in value:
            _validate(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > MAX_CONTAINER_ITEMS:
            raise StrictJsonError("JSON object exceeds the member limit.")
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictJsonError("JSON object keys must be strings.")
            _validate(key, depth + 1)
            _validate(item, depth + 1)
        return
    raise StrictJsonError(f"Unsupported JSON value type: {type(value).__name__}.")


def loads_object(data: str | bytes, *, label: str = "JSON", maximum_bytes: int = MAX_BYTES) -> dict[str, Any]:
    encoded = data.encode("utf-8") if isinstance(data, str) else data
    if len(encoded) > maximum_bytes:
        raise StrictJsonError(f"{label} exceeds {maximum_bytes} bytes.")
    try:
        value = json.loads(encoded, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, StrictJsonError) as exc:
        if isinstance(exc, StrictJsonError):
            raise
        raise StrictJsonError(f"Invalid {label}: {exc}.") from exc
    if type(value) is not dict:
        raise StrictJsonError(f"{label} root must be an object.")
    _validate(value)
    return value


def read_object(path: Path | str, *, maximum_bytes: int = MAX_BYTES) -> dict[str, Any]:
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise StrictJsonError(f"Unable to read JSON source {source}: {exc}.") from exc
    return loads_object(data, label=str(source), maximum_bytes=maximum_bytes)
