# Release Candidate 2.0 (Gold Master)

Built: 2026-01-04T02:35:33Z

## Included
- Phase 2 Pattern 2 implementation (Disk is truth)
- Strict recorder: `tools/sim_robot_final.py`
- Strict discovery judge: `src/axm_compile/streams.py`
- Compiler integration: emits `evidence/streams.parquet`
- Board demo script: `scripts/board_demo.sh`
- Acceptance test: `tests/test_phase2_pattern2.py`

## Demo contract
- Safe run produces `cam_residuals.bin` of 0 bytes.
- Crash run records exactly the configured pre/post windows.
- Residuals are discovered via scan, not referenced by JSON offsets.
- Any drift or corruption aborts compilation.
