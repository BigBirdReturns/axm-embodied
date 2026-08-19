from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
CI = WORKFLOW_ROOT / "ci.yml"


def test_ordinary_ci_is_the_single_clean_action_evidence_supergate() -> None:
    text = CI.read_text(encoding="utf-8")

    assert "${{ runner.temp }}/rodoh-action-evidence" in text
    assert "${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert "tests/test_strict_action_json.py" in text
    assert "tests/test_action_session.py" in text
    assert "tests/test_action_spool.py" in text
    assert "python -m pytest tests/ -q" in text
    assert 'test -z "$(git status --porcelain)"' in text
    assert "axm-embodied-action-evidence-qualification/1" in text
    assert "kernel-boundary-drift" in text
    assert "rodoh-action-evidence-custody" in text

    for superseded in (
        "rodoh-action-evidence.yml",
        "rodoh-action-session.yml",
        "rodoh-action-spool.yml",
        "rodoh-action-strict-json.yml",
    ):
        assert not (WORKFLOW_ROOT / superseded).exists()
