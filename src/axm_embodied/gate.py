"""Law Gate — governance-aware arming authority.

The gate answers one question: *is this robot allowed to move under this
envelope?* Its doctrine is **no proof, no motion**:

1. The envelope shard must verify against a trust anchor held in the
   robot's governance directory — not against the shard's own key.
2. The anchor's fingerprint must be enrolled in ``trust_store.json``.
3. The envelope's constraint claims must sit at or below the actuation
   tier permitted by ``local_policy.json`` (Tier 0 = formal invariants;
   a policy of ``max_actuation_tier: 0`` means the robot may only move
   under formally derived law, never under advisory claims).

Governance directory layout::

    governance/
    ├── trust_store.json          # {"trusted_publishers": ["<sha256 hex>", ...]}
    ├── local_policy.json         # {"max_actuation_tier": 0}
    └── trusted_keys/
        └── <name>.pub            # 1344-byte axm-hybrid1 public keys
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from axm_embodied.envelope import EnvelopeError, SafetyEnvelope


class GateError(Exception):
    """The Law Gate refused to arm."""


@dataclass(frozen=True)
class Clearance:
    """Proof that the Law Gate authorized actuation under an envelope."""
    envelope: SafetyEnvelope
    trusted_key_path: Path
    max_actuation_tier: int
    granted_at: str


class LawGate:
    def __init__(self, governance_dir: Path | str):
        self.governance_dir = Path(governance_dir)
        self.trust_store_path = self.governance_dir / "trust_store.json"
        self.policy_path = self.governance_dir / "local_policy.json"
        self.keys_dir = self.governance_dir / "trusted_keys"

        if not self.trust_store_path.exists():
            raise GateError(f"no trust store at {self.trust_store_path}")
        store = json.loads(self.trust_store_path.read_text())
        self.trusted_fingerprints: List[str] = list(store.get("trusted_publishers", []))
        if not self.trusted_fingerprints:
            raise GateError("trust store lists no trusted publishers")

        policy = (
            json.loads(self.policy_path.read_text())
            if self.policy_path.exists()
            else {}
        )
        self.max_actuation_tier: int = int(policy.get("max_actuation_tier", 0))

    def _trusted_keys(self) -> Dict[str, Path]:
        """Enrolled anchors: fingerprint -> key path.

        A key file on disk that is NOT listed in trust_store.json is
        ignored — dropping a .pub into the directory is not enrollment.
        """
        out: Dict[str, Path] = {}
        if not self.keys_dir.is_dir():
            return out
        for pub in sorted(self.keys_dir.glob("*.pub")):
            fp = hashlib.sha256(pub.read_bytes()).hexdigest()
            if fp in self.trusted_fingerprints:
                out[fp] = pub
        return out

    def authorize(self, bounds_shard: Path | str) -> Clearance:
        """Verify the envelope against enrolled anchors and check policy.

        Raises :class:`GateError` (and never returns) unless every check
        passes. The robot's runtime arms only on a returned Clearance.
        """
        bounds_shard = Path(bounds_shard)

        # The shard names its publisher; trust is decided by OUR store.
        pub_path = bounds_shard / "sig" / "publisher.pub"
        if not pub_path.exists():
            raise GateError(f"no publisher key in shard: {pub_path}")
        shard_fp = hashlib.sha256(pub_path.read_bytes()).hexdigest()

        anchors = self._trusted_keys()
        if not anchors:
            raise GateError(
                f"no enrolled trust anchors under {self.keys_dir} "
                f"(keys must exist AND be fingerprinted in trust_store.json)"
            )
        anchor = anchors.get(shard_fp)
        if anchor is None:
            raise GateError(
                f"shard publisher fingerprint {shard_fp[:16]}… is not an "
                f"enrolled trust anchor — refusing to arm"
            )

        try:
            envelope = SafetyEnvelope.load(bounds_shard, trusted_key_path=anchor)
        except EnvelopeError as e:
            raise GateError(f"envelope rejected: {e}") from e

        if envelope.max_tier > self.max_actuation_tier:
            raise GateError(
                f"envelope constraints are Tier {envelope.max_tier} but local "
                f"policy permits actuation only under Tier "
                f"{self.max_actuation_tier} law"
            )

        return Clearance(
            envelope=envelope,
            trusted_key_path=anchor,
            max_actuation_tier=self.max_actuation_tier,
            granted_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        )


def enroll_key(governance_dir: Path | str, pub_key_path: Path | str, name: str | None = None) -> str:
    """Enroll a publisher public key as a trust anchor. Returns its fingerprint.

    Copies the key into governance/trusted_keys/ and appends its SHA-256
    fingerprint to trust_store.json. This is the ONLY sanctioned way keys
    enter the trust store.
    """
    governance_dir = Path(governance_dir)
    pub_key_path = Path(pub_key_path)
    keys_dir = governance_dir / "trusted_keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    blob = pub_key_path.read_bytes()
    fp = hashlib.sha256(blob).hexdigest()
    dest = keys_dir / f"{name or pub_key_path.stem}.pub"
    dest.write_bytes(blob)

    store_path = governance_dir / "trust_store.json"
    store = (
        json.loads(store_path.read_text())
        if store_path.exists()
        else {"trusted_publishers": []}
    )
    if fp not in store["trusted_publishers"]:
        store["trusted_publishers"].append(fp)
    store_path.write_text(json.dumps(store, indent=2) + "\n")
    return fp
