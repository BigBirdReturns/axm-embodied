"""
axm-embodied/src/axm_core/ids.py

Backward-compatible identity shim.

Delegates entity_id and claim_id to the canonical genesis hub
(axm_verify.identity) so hash outputs remain identical across
axm-core and axm-embodied. Verified safe by Unicode diff:
NFKC vs NFC divergence does not affect ASCII telemetry domain.

span_id and prov_id have no genesis equivalent — physical telemetry
byte ranges are embodied-specific. They stay local.

Import contract for all embodied callers is unchanged:
    # legacy fallback removed — delegates to axm_verify.identity via shim
"""
from __future__ import annotations

import base64
import hashlib

# ── Delegate to genesis hub ───────────────────────────────────────────────
from axm_verify.identity import (
    recompute_entity_id as entity_id,
    recompute_claim_id as claim_id,
    canonicalize,
)

# ── Embodied-specific: byte-range identity ────────────────────────────────
# These functions address physical telemetry byte positions.
# No genesis equivalent exists. They remain local and frozen.

def _hash(b: bytes, prefix: str) -> str:
    """Compute truncated SHA-256 hash with base32 encoding.
    Algorithm is frozen — changing this breaks all historical shard IDs.
    """
    h = hashlib.sha256(b).digest()[:15]
    return prefix + base64.b32encode(h).decode("ascii").lower().rstrip("=")


def span_id(src_hash: str, start: int, end: int, text: str) -> str:
    """Generate deterministic span ID from source hash + byte range + text.

    Frozen. Identical to original embodied implementation.
    Changing this invalidates all historical evidence/spans.parquet joins.
    """
    payload = f"{src_hash}\x00{start}\x00{end}\x00{text}"
    return _hash(payload.encode("utf-8"), "s_")


def prov_id(cid: str, sid: str) -> str:
    """Generate deterministic provenance ID from claim + span.

    Frozen. Identical to original embodied implementation.
    """
    payload = f"{cid}\x00{sid}"
    return _hash(payload.encode("utf-8"), "p_")
