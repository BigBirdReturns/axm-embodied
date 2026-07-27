from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rodoh-action-evidence.yml"


def test_action_evidence_workflow_is_the_single_clean_supergate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "${{ runner.temp }}/rodoh-action-evidence" in text
    assert "tests/test_strict_action_json.py" in text
    assert "tests/test_action_session.py" in text
    assert "tests/test_action_spool.py" in text
    assert "python -m pytest -q 2>&1" in text
    assert 'test -z "$(git status --porcelain)"' in text
    assert "axm-embodied-action-evidence-qualification/1" in text

    for superseded in (
        "rodoh-action-session.yml",
        "rodoh-action-spool.yml",
        "rodoh-action-strict-json.yml",
    ):
        assert not (WORKFLOW.parent / superseded).exists()
