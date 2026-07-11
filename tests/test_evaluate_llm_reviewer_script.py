from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_llm_reviewer.py"
SPEC = importlib.util.spec_from_file_location("evaluate_llm_reviewer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _case(sample_id: str, reason: str, selected: bool = True) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "selection_reason": reason,
        "selected_for_review": selected,
    }


def test_small_scale_selection_is_balanced_and_deterministic() -> None:
    cases = [
        _case("a1", "disagreement"),
        _case("a2", "disagreement"),
        _case("a3", "disagreement"),
        _case("b1", "unscorable"),
        _case("c1", "context_risk"),
        _case("ignored", "disagreement", selected=False),
    ]

    subset = MODULE.select_small_scale_cases(cases, 4)

    assert [case["sample_id"] for case in subset] == ["c1", "a1", "b1", "a2"]


def test_small_scale_selection_rejects_non_positive_limit() -> None:
    try:
        MODULE.select_small_scale_cases([_case("a", "reason")], 0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_small_scale_selection_excludes_prior_responses() -> None:
    cases = [_case("prior", "a"), _case("fresh", "a")]

    subset = MODULE.select_small_scale_cases(
        cases, 1, frozenset({"prior"})
    )

    assert [case["sample_id"] for case in subset] == ["fresh"]
