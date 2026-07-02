"""Query a compiled shard: what does the record actually prove?

Shard core tables are canonical JSONL (spec/v1) — plain files, no query
engine required. This example answers two questions a lawyer or an
insurer asks first:

  1. What safety envelope was in force? (references@1 citations)
  2. What did the robot observe, choose, and breach, with evidence?

Usage:
    python examples/query.py <shard_path> [predicate]
    python examples/query.py demo/flight_fault/incident-shard breached_envelope
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python query.py <shard_path> [predicate]")
        print("Example: python query.py incident-shard/ breached_envelope")
        sys.exit(1)

    shard = Path(sys.argv[1])
    predicate = sys.argv[2] if len(sys.argv) > 2 else None

    entities = {r["entity_id"]: r["label"] for r in load_jsonl(shard / "graph" / "entities.jsonl")}
    claims = load_jsonl(shard / "graph" / "claims.jsonl")
    provenance = load_jsonl(shard / "graph" / "provenance.jsonl")
    references = load_jsonl(shard / "ext" / "references@1.jsonl")

    # Evidence text per claim, via provenance byte ranges -> spans.
    span_by_range = {
        (r["source_hash"], r["byte_start"], r["byte_end"]): r["text"]
        for r in load_jsonl(shard / "evidence" / "spans.jsonl")
    }
    evidence_by_claim: dict[str, str] = {}
    for p in provenance:
        key = (p["source_hash"], p["byte_start"], p["byte_end"])
        if key in span_by_range and p["claim_id"] not in evidence_by_claim:
            evidence_by_claim[p["claim_id"]] = span_by_range[key]

    if references:
        print("--- Cross-shard citations (references@1) ---")
        for r in references:
            print(f"  {r['relation_type']}: {r['dst_shard_id']}")
            if r.get("note"):
                print(f"    note: {r['note']}")
        print()

    shown = 0
    print(f"--- Claims{f' (predicate={predicate})' if predicate else ''} ---")
    for c in claims:
        if predicate and c["predicate"] != predicate:
            continue
        subj = entities.get(c["subject"], c["subject"])
        obj = entities.get(c["object"], c["object"])
        print(f"  [{c['tier']}] {subj} --{c['predicate']}--> {obj}")
        ev = evidence_by_claim.get(c["claim_id"])
        if ev:
            print(f"      evidence: {ev[:100]}{'…' if len(ev) > 100 else ''}")
        shown += 1
        if shown >= 25 and not predicate:
            print(f"  … {len(claims) - shown} more (pass a predicate to filter)")
            break

    if shown == 0:
        print("  No matching claims.")


if __name__ == "__main__":
    main()
