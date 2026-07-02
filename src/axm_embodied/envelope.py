"""Safety envelope loader — the runtime's view of a bounds shard.

An envelope is only ever constructed from a shard that has just passed
full kernel verification (`axm_verify.logic.verify_shard`) against a
trusted key supplied out of band. There is no code path that yields a
:class:`SafetyEnvelope` from unverified bytes: if the Merkle root, the
hybrid signature, or any canonical table is off by one byte, the load
raises and the robot never arms.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping

import blake3

from axm_verify.logic import verify_shard

from axm_embodied.bounds import BOUND_PREDICATE, BOUNDS_NAMESPACE


class EnvelopeError(Exception):
    """The bounds shard failed verification or does not encode an envelope."""


@dataclass(frozen=True)
class SafetyEnvelope:
    """A verified, signed safety envelope: per-action L∞ bounds.

    ``shard_id`` is the derived sh1_ identity of the bounds shard; every
    incident recorded under this envelope cites it, so the forensic chain
    runs: training capsules → bounds shard → incident shard.
    """
    shard_path: Path
    shard_id: str
    publisher_id: str
    publisher_fingerprint: str            # SHA-256 hex of sig/publisher.pub
    bounds: Mapping[str, float]           # action class -> max latent L∞
    sample_counts: Mapping[str, int] = field(default_factory=dict)
    max_tier: int = 0                     # highest tier among bound claims

    def bound_for(self, action: str) -> float | None:
        return self.bounds.get(action)

    @classmethod
    def load(cls, shard_path: Path | str, trusted_key_path: Path | str) -> "SafetyEnvelope":
        """Verify the shard with the kernel verifier, then parse the envelope.

        ``trusted_key_path`` is the out-of-band trust anchor (a governance
        key, never the shard's own publisher.pub — that would only prove
        the shard agrees with itself).
        """
        shard_path = Path(shard_path)
        result = verify_shard(shard_path, trusted_key_path=Path(trusted_key_path))
        if result["status"] != "PASS":
            raise EnvelopeError(
                f"bounds shard failed verification: "
                f"{[e['code'] for e in result['errors']]}"
            )

        manifest = json.loads((shard_path / "manifest.json").read_bytes())
        shard_id = "sh1_" + blake3.blake3(
            (shard_path / "manifest.json").read_bytes()
        ).hexdigest()
        pub_bytes = (shard_path / "sig" / "publisher.pub").read_bytes()
        fingerprint = hashlib.sha256(pub_bytes).hexdigest()

        if manifest["metadata"].get("namespace") != BOUNDS_NAMESPACE:
            raise EnvelopeError(
                f"shard namespace is {manifest['metadata'].get('namespace')!r}, "
                f"expected {BOUNDS_NAMESPACE!r} — not a bounds shard"
            )

        # entities: id -> label ("bounds/<action>")
        labels: Dict[str, str] = {}
        with (shard_path / "graph" / "entities.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                labels[row["entity_id"]] = row["label"]

        bounds: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        max_tier = 0
        with (shard_path / "graph" / "claims.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                subj_label = labels.get(row["subject"], "")
                if not subj_label.startswith("bounds/"):
                    continue
                action = subj_label[len("bounds/"):]
                if row["predicate"] == BOUND_PREDICATE:
                    if row["object_type"] != "literal:decimal":
                        raise EnvelopeError(
                            f"bound claim for {action!r} has object_type "
                            f"{row['object_type']!r}, expected literal:decimal"
                        )
                    bounds[action] = float(row["object"])
                    max_tier = max(max_tier, int(row["tier"]))
                elif row["predicate"] == "sample_count":
                    counts[action] = int(row["object"])

        if not bounds:
            raise EnvelopeError("shard verifies but contains no bound claims")

        return cls(
            shard_path=shard_path,
            shard_id=shard_id,
            publisher_id=manifest["publisher"]["id"],
            publisher_fingerprint=fingerprint,
            bounds=bounds,
            sample_counts=counts,
            max_tier=max_tier,
        )
