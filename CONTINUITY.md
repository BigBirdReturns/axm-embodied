# axm-embodied continuity

`axm-embodied` is the AXM Estate's physical-evidence organ. It compiles and preserves bounded observations about bodies, devices, environments, sessions, and physical execution while keeping domain interpretation and accepted outcomes outside this repository.

## Authority membrane

This organ owns:

- the `embodied@1` spoke contract and its continuity;
- bounded physical-observation schemas and profiles;
- compilation of embodied evidence into Genesis-verifiable products;
- repository-local validation and kernel-boundary drift checks;
- publication of its static explanatory surface.

This organ does not own:

- game, campaign, policy, medical, legal, or operational truth;
- an accepted action result;
- Arc campaign mutation;
- semantic interpretation of opaque sensor captures;
- permission to turn a tracking, focus, guardian, or device stop into a domain failure;
- authority merely because it recorded or transported an observation.

A physical observation is evidence with a source and limitation. It is not a verdict.

## Source and verification

The default branch is the accepted repository line. The ordinary `.github/workflows/ci.yml` workflow installs the exact pinned Genesis kernel, runs the complete repository tests, and executes the Genesis drift check. A successor must not change the kernel pin, profile contract, or continuity law without running that complete boundary.

The static documentation site is published by `.github/workflows/pages.yml`. A Pages failure is a publication defect. It does not establish failure of evidence custody, although it must remain visible until repaired.

## Post-v1 donor boundary

Post-v1 action-session, spool, strict-JSON, journal, and Quest-return work may exist on draft donor branches or pull requests. Those branches are not current-main capability merely because their source exists or their focused tests pass. Activation requires the coordinated authority and physical receipts named by the governing acceptance issue.

In particular, a provisional Unity or Quest execution candidate must retain `Arc replay required`; `axm-embodied` may preserve that candidate and the later accepted Arc receipt, but it cannot issue the accepted outcome itself.

## Recovery

A successor should begin with:

```bash
git status --short
git log -1 --oneline
python -m pip install --upgrade pip
pip install '../axm-genesis[mldsa-compat]'
pip install -e . --no-deps
pip install pytest numpy click
python -m pytest tests/ -q
bash ../axm-genesis/tools/drift-check.sh .
```

Use the exact Genesis commit pinned by the current workflow rather than a nearby checkout. Preserve failing receipts and source limitations. Do not repair a red publication job by weakening the evidence or kernel gate.

## Succession checklist

Before transferring maintenance, record:

1. exact repository head and Genesis pin;
2. current schema and profile versions;
3. complete CI and drift results;
4. active donor branches and the acceptance condition for each;
5. machine-bound observations that remain uncollected;
6. any opaque attachments and the tool required to inspect them;
7. unresolved license, privacy, retention, or device constraints;
8. the next safe rollback point.

The repository must remain reconstructable without the original author, their workstation, or an undocumented cloud service.

## Control question

Can a successor preserve and verify the physical record, explain its limits, and continue the organ without acquiring authority over the meaning or outcome of what was observed?
