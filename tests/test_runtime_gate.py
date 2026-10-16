from pathlib import Path
import json
import shutil

from opinion_agent.evaluation.runtime_gate import evaluate_runtime_gate
from opinion_agent.evaluation.runtime_tasks import canonical_text_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_gate_report_is_reproducible_and_paired() -> None:
    report = evaluate_runtime_gate(PROJECT_ROOT)
    committed = json.loads(
        (PROJECT_ROOT / "data/evaluation/runtime_eval_report_v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert report == committed
    assert report["status"] == "passed"
    assert report["evaluation_mode"] == "synthetic_contract_fixture"
    assert report["gate"]["paired_cases"] == 60
    assert report["gate"]["failures"] == []
    assert len(report["gate"]["category_deltas"]) == 6
    assert report["gate"]["deltas"]["mean_latency_ms"] == 35
    assert report["gate"]["deltas"]["mean_cost_usd"] < 0.01


def test_runtime_gate_report_preserves_evidence_limitations() -> None:
    report = evaluate_runtime_gate(PROJECT_ROOT)

    assert any("not production traffic" in item for item in report["limitations"])
    assert any("not production SLA evidence" in item for item in report["limitations"])


def test_runtime_evidence_hash_is_cross_platform_line_ending_stable(
    tmp_path: Path,
) -> None:
    lf = tmp_path / "lf.jsonl"
    crlf = tmp_path / "crlf.jsonl"
    lf.write_bytes(b'{"case_id":"a"}\n')
    crlf.write_bytes(b'{"case_id":"a"}\r\n')

    assert canonical_text_sha256(lf) == canonical_text_sha256(crlf)


def test_runtime_gate_blocks_a_degraded_candidate(tmp_path: Path) -> None:
    for relative in (
        "examples/runtime_eval_tasks_v1.jsonl",
        "examples/runtime_eval_baseline_v1.jsonl",
        "examples/runtime_eval_candidate_v1.jsonl",
        "data/evaluation/runtime_eval_tasks_v1_manifest.json",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PROJECT_ROOT / relative, destination)

    candidate_path = tmp_path / "examples/runtime_eval_candidate_v1.jsonl"
    records = [
        json.loads(line)
        for line in candidate_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records[0]["succeeded"] = False
    records[0]["quality_score"] = 0.0
    records[0]["error_count"] = 1
    candidate_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    report = evaluate_runtime_gate(tmp_path)

    assert report["status"] == "blocked"
    assert set(report["gate"]["failures"]) == {
        "success_rate_regression",
        "error_rate_regression",
    }
