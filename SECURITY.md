# Security & Forensics Notes

## Bounded reads
Residual payload lengths are capped to prevent memory exhaustion attacks.

## Disk as truth
Evidence discovery scans binary streams directly. Logs are narrative only.

## Resynchronization
Residual scanning resynchronizes after corruption to recover valid records.

## Durability
fsync is used on hot paths to improve power‑loss survivability.
Full guarantees require appropriate hardware.

## Non‑goals
This project does not claim perfect crash survivability on consumer hardware.
