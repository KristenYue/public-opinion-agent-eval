"""Measure local serial opinion-agent latency, routing, and provider usage."""

from __future__ import annotations

from argparse import ArgumentParser
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.evaluation.performance import summarize_runs  # noqa: E402
from opinion_agent.retrieval import TfidfEventRetriever  # noqa: E402
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


DEFAULT_CASES = PROJECT_ROOT / "examples" / "demo_cases"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "performance_baseline_offline.json"


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmup < 0:
        raise SystemExit("repeats must be >=1 and warmup must be >=0")

    requests = load_requests(args.cases)
    graph = build_graph()
    for index in range(args.warmup):
        graph.invoke(make_state(requests[index % len(requests)]))

    records = []
    for _ in range(args.repeats):
        for request in requests:
            state = make_state(request)
            started = perf_counter()
            result = graph.invoke(state)
            records.append(
                {
                    "case": request.get("event_id"),
                    "wall_latency_ms": (perf_counter() - started) * 1000,
                    "result": result,
                }
            )

    payload = {
        "protocol": "local_serial_offline_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "llm_enabled": False,
            "retriever": "tfidf",
            "concurrency": 1,
            "warmup_runs": args.warmup,
            "measured_cases": len(requests),
            "repeats_per_case": args.repeats,
            "limitations": [
                "Local serial latency is not production throughput or QPS.",
                "No external LLM was called, so provider token usage and Qwen latency are zero.",
                "Synthetic public demo cases are used; this is an engineering baseline, not a model-quality evaluation.",
            ],
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "summary": summarize_runs(records),
        "runs": [
            {
                "case": record["case"],
                "wall_latency_ms": round(record["wall_latency_ms"], 3),
                "review_status": record["result"].get("analysis_report", {}).get("review_status"),
                "errors": record["result"].get("errors", []),
            }
            for record in records
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output}")


def load_requests(cases_dir: Path) -> list[dict[str, object]]:
    requests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(cases_dir.glob("*/request.json"))
    ]
    if not requests:
        raise FileNotFoundError(f"no request.json files found under {cases_dir}")
    return requests


def make_state(request: dict[str, object]) -> dict[str, object]:
    state = deepcopy(request)
    state["request_id"] = f"perf-{uuid.uuid4().hex}"
    state["tool_traces"] = []
    state["errors"] = []
    return state


def build_graph():
    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    retriever = TfidfEventRetriever(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl")
    return build_opinion_graph(
        classifier,
        retriever,
        SnowNLPSentimentClassifier(),
        reviewer=None,
    )


if __name__ == "__main__":
    main()
