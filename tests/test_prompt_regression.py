from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.prompt_regression import evaluate_prompt_regression  # noqa: E402


def test_current_prompt_and_frozen_evidence_pass_gate() -> None:
    result = evaluate_prompt_regression(PROJECT_ROOT)

    assert result["passed"] is True
    assert result["prompt_version"] == "event_stance_v2"


def test_prompt_source_change_blocks_gate(tmp_path) -> None:
    paths = [
        "src/opinion_agent/agent/reviewer.py",
        "data/evaluation/prompt_regression_baseline.json",
        "data/evaluation/reviewer_confidence_diagnostics.json",
    ]
    for relative in paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, destination)
    reviewer = tmp_path / "src/opinion_agent/agent/reviewer.py"
    reviewer.write_text(
        reviewer.read_text(encoding="utf-8").replace(
            "You are a Chinese sentiment adjudicator.",
            "You are a changed sentiment adjudicator.",
        ),
        encoding="utf-8",
    )

    result = evaluate_prompt_regression(tmp_path)

    assert result["passed"] is False
    assert "prompt contract source changed" in result["failures"][0]
