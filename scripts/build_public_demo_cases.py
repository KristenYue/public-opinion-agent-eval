"""Build public synthetic demo cases with run-audit outputs."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.evaluation.run_audit import audit_agent_run  # noqa: E402
from opinion_agent.retrieval import TfidfEventRetriever  # noqa: E402
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "examples" / "demo_cases"


CASES = [
    {
        "slug": "01_conservative_policy_manual_review",
        "title": "保守策略：高分歧时进入人工复核",
        "policy_env": {
            "REVIEW_DISAGREEMENT_THRESHOLD": "0.8",
            "REVIEW_ROUTE_ON_NO_EVIDENCE": "0",
            "EVENT_CARDS_PATH": str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"),
        },
        "request": {
            "request_id": "demo-policy-auto-release",
            "event_id": "public-demo-policy-change",
            "query": "分析某公共服务政策调整的舆情反馈，并检索可参考的历史事件。",
            "comments": [
                {
                    "sample_id": "demo-1",
                    "text": "目前信息还不完整，先看后续细则和配套说明。",
                },
                {
                    "sample_id": "demo-2",
                    "text": "如果补贴能及时跟上，整体影响可能可控。",
                },
                {
                    "sample_id": "demo-3",
                    "text": "希望官方尽快解释具体执行方式。",
                },
            ],
        },
        "explanation": [
            "这个案例用于展示默认业务安全策略：当模型分歧很高时进入 manual_required。",
            "即使评论看起来不激烈，只要主模型和辅助信号不一致，系统也不会直接给最终结论。",
            "自动放行能力由 data/evaluation/agent_mvp_policy_experiment_tfidf_threshold_08.json 证明，不在单条合成 demo 中硬造。",
        ],
    },
    {
        "slug": "02_model_disagreement_manual_review",
        "title": "模型分歧：触发 manual_required",
        "policy_env": {
            "EVENT_CARDS_PATH": str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"),
        },
        "request": {
            "request_id": "demo-model-disagreement",
            "event_id": "public-demo-service-complaint",
            "query": "分析服务体验争议下的负面舆情风险，并给出是否需要复核的判断。",
            "comments": [
                {
                    "sample_id": "demo-1",
                    "text": "客服一直没有解决问题，真的很失望。",
                },
                {
                    "sample_id": "demo-2",
                    "text": "流程说明反复变化，普通用户根本不知道该怎么处理。",
                },
                {
                    "sample_id": "demo-3",
                    "text": "这次回应太慢了，希望有人能认真跟进。",
                },
            ],
        },
        "explanation": [
            "这个案例展示模型分歧、负面风险或短文本上下文风险如何进入复核队列。",
            "系统不会把主模型原始情绪直接当最终结论，而是标记 manual_required。",
            "演示重点是解释 uncertainty-aware routing，而不是声称模型永远正确。",
        ],
    },
    {
        "slug": "03_no_evidence_fallback",
        "title": "证据缺失：no_retrieval_evidence fallback",
        "policy_env": {
            "EVENT_CARDS_PATH": str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"),
        },
        "retriever": "none",
        "request": {
            "request_id": "demo-no-evidence",
            "event_id": "public-demo-new-niche-topic",
            "query": "分析一个全新小众议题的舆情风险，观察检索不到历史证据时系统如何处理。",
            "comments": [
                {
                    "sample_id": "demo-1",
                    "text": "这个新规则看起来影响范围很窄，但解释不够透明。",
                },
                {
                    "sample_id": "demo-2",
                    "text": "目前没有看到类似案例，建议先谨慎观察。",
                },
            ],
        },
        "explanation": [
            "这个案例展示 RAG 检索不到可靠证据时的 fallback。",
            "这里使用受控 no-evidence retriever 演示系统边界：没有证据时显式暴露 no_retrieval_evidence，而不是编造历史案例。",
            "演示重点是 evidence grounding 和 citation integrity。",
        ],
    },
]


def main() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    index = []

    original_env = {key: os.environ.get(key) for key in _all_policy_keys()}
    try:
        for case in CASES:
            _apply_env(case["policy_env"])
            graph = _build_demo_graph(str(case.get("retriever", "tfidf")))

            request = deepcopy(case["request"])
            request["request_id"] = f"{request['request_id']}-{uuid.uuid4().hex[:8]}"
            state = {
                **request,
                "tool_traces": [],
                "errors": [],
            }
            result = graph.invoke(state)
            audit = audit_agent_run(state, result)

            case_dir = OUTPUT_ROOT / case["slug"]
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(case_dir / "request.json", request)
            _write_json(case_dir / "result.json", result)
            _write_json(case_dir / "audit.json", audit)
            (case_dir / "README.md").write_text(
                _case_readme(case, audit),
                encoding="utf-8",
            )
            index.append(
                {
                    "slug": case["slug"],
                    "title": case["title"],
                    "review_status": audit["review"]["review_status"],
                    "risk_flags": audit["risk_flags"],
                    "contract_passed": audit["contract"]["passed"],
                }
            )
    finally:
        _restore_env(original_env)

    _write_json(OUTPUT_ROOT / "index.json", {"cases": index})
    (OUTPUT_ROOT / "README.md").write_text(_index_readme(index), encoding="utf-8")
    print(f"Wrote demo cases to {OUTPUT_ROOT}")


def _all_policy_keys() -> set[str]:
    return {
        "EVENT_CARDS_PATH",
        "REVIEW_DISAGREEMENT_THRESHOLD",
        "REVIEW_ROUTE_ON_NO_EVIDENCE",
    }


def _apply_env(values: dict[str, str]) -> None:
    for key in _all_policy_keys():
        os.environ.pop(key, None)
    for key, value in values.items():
        os.environ[key] = value


def _restore_env(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class NoEvidenceRetriever:
    def retrieve(self, query: str, top_k: int = 3, exclude_event_id: str | None = None):
        return []


def _build_demo_graph(retriever_name: str = "tfidf"):
    cards_path = Path(
        os.environ.get(
            "EVENT_CARDS_PATH",
            str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"),
        )
    )
    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    retriever = NoEvidenceRetriever() if retriever_name == "none" else TfidfEventRetriever(cards_path)
    secondary = SnowNLPSentimentClassifier()
    return build_opinion_graph(classifier, retriever, secondary)


def _case_readme(case: dict[str, object], audit: dict[str, object]) -> str:
    explanation = "\n".join(f"- {item}" for item in case["explanation"])
    return f"""# {case["title"]}

## 用途

{explanation}

## 关键结果

- review_status: `{audit["review"]["review_status"]}`
- risk_flags: `{", ".join(audit["risk_flags"]) or "none"}`
- contract_passed: `{audit["contract"]["passed"]}`
- tool_success_rate: `{audit["scorecard"]["tool_success_rate"]}`

## 文件

- `request.json`: 输入事件和合成评论。
- `result.json`: Agent 原始输出。
- `audit.json`: 单次运行审计结果。
"""


def _index_readme(index: list[dict[str, object]]) -> str:
    rows = "\n".join(
        f"| `{item['slug']}` | {item['title']} | `{item['review_status']}` | `{', '.join(item['risk_flags']) or 'none'}` |"
        for item in index
    )
    return f"""# Public Demo Cases

这些案例使用合成公开评论，用于 README 和本地演示，不依赖私有微博语料。

| Case | 说明 | review_status | risk_flags |
|---|---|---|---|
{rows}

生成命令：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\build_public_demo_cases.py
```
"""


if __name__ == "__main__":
    main()
