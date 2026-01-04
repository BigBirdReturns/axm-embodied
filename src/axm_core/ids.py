"""AXM Embodied Genesis - Deterministic Identity Functions."""
from __future__ import annotations

import base64
import hashlib
import unicodedata


def canonicalize(text: str) -> str:
    """Canonicalize text per AXM spec: NFKC, casefold, whitespace normalize."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(t.split())


def _hash(b: bytes, prefix: str) -> str:
    """Compute truncated SHA-256 hash with base32 encoding."""
    h = hashlib.sha256(b).digest()[:15]
    return prefix + base64.b32encode(h).decode("ascii").lower().rstrip("=")


def entity_id(ns: str, label: str) -> str:
    """Generate deterministic entity ID from namespace and label."""
    payload = canonicalize(ns) + "\x00" + canonicalize(label)
    return _hash(payload.encode("utf-8"), "e_")


def claim_id(sub: str, pred: str, obj: str, obj_type: str) -> str:
    """Generate deterministic claim ID."""
    obj_clean = obj if obj_type == "entity" else canonicalize(obj)
    payload = f"{sub}\x00{canonicalize(pred)}\x00{obj_type}\x00{obj_clean}"
    return _hash(payload.encode("utf-8"), "c_")


def span_id(src_hash: str, start: int, end: int, text: str) -> str:
    """Generate deterministic span ID."""
    payload = f"{src_hash}\x00{start}\x00{end}\x00{text}"
    return _hash(payload.encode("utf-8"), "s_")


def prov_id(cid: str, sid: str) -> str:
    """Generate deterministic provenance ID."""
    payload = f"{cid}\x00{sid}"
    return _hash(payload.encode("utf-8"), "p_")
