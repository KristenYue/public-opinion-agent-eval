"""Run a real in-process API request with local models and no external LLM."""

from pathlib import Path
import json
import os
import sys

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from opinion_agent.api import app  # noqa: E402


def main() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        health.raise_for_status()
        response = client.post(
            "/v1/analyze",
            json={
                "event_id": "关税",
                "query": "分析关税事件评论，并检索可信的历史相似事件",
                "comments": [
                    {"sample_id": "demo-1", "text": "这个政策让普通消费者压力更大"},
                    {"sample_id": "demo-2", "text": "先看看后续具体实施细则"},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        compact = {
            "health": health.json(),
            "event_id": body["event_id"],
            "route_decision": body["route_decision"],
            "final_report": body["final_report"],
            "trace_nodes": [trace["node"] for trace in body["tool_traces"]],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
