"""Query the Law Gate - find mandatory actions for an event type."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python query.py <shard_path> <event_type>")
        print("Example: python query.py shard/ wheel_slip")
        sys.exit(1)

    shard = Path(sys.argv[1])
    event_type = sys.argv[2]

    con = duckdb.connect(":memory:")

    # Load shard tables
    con.execute(f"CREATE VIEW entities AS SELECT * FROM '{shard}/graph/entities.parquet'")
    con.execute(f"CREATE VIEW claims AS SELECT * FROM '{shard}/graph/claims.parquet'")
    con.execute(f"CREATE VIEW spans AS SELECT * FROM '{shard}/evidence/spans.parquet'")
    con.execute(f"CREATE VIEW provenance AS SELECT * FROM '{shard}/graph/provenance.parquet'")

    # The Law Gate Query: mandatory actions (Tier <= 1) for this event
    sql = f"""
    SELECT 
        t2.label AS action,
        c.tier,
        s.text AS evidence
    FROM claims c
    JOIN entities t1 ON c.subject = t1.entity_id
    JOIN entities t2 ON c.object = t2.entity_id
    LEFT JOIN provenance p ON p.claim_id = c.claim_id
    LEFT JOIN spans s ON s.span_id = p.span_id
    WHERE t1.label = '{event_type}' 
      AND c.predicate = 'resolved_by'
      AND c.tier <= 1
    """

    print(f"--- Law Gate Query: {event_type} ---")
    print(f"--- Tier <= 1 (Safety Rules) ---\n")

    df = con.execute(sql).fetchdf()
    if df.empty:
        print("No mandatory actions found.")
        print("Robot must enter SAFE STATE.")
    else:
        for _, row in df.iterrows():
            print(f"ACTION: {row['action']}")
            print(f"  Tier: {row['tier']}")
            print(f"  Evidence: {row['evidence'][:80]}...")
            print()


if __name__ == "__main__":
    main()
