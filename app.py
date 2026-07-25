"""Gradio entrypoint for the public opinion-analysis Agent demo."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import gradio as gr


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault(
    "EVENT_CARDS_PATH", str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl")
)
# The public Space must not block its first request on an external model
# download. The full project keeps hybrid BGE retrieval as the API default.
os.environ.setdefault("RETRIEVER_BACKEND", "tfidf")
os.environ.setdefault("REVIEW_CONFIDENCE_THRESHOLD", "0.80")
os.environ.setdefault("ENABLE_OFFLINE_DEMO_REVIEWER", "1")

from opinion_agent.api import get_default_graph  # noqa: E402
from opinion_agent.agent.nodes import apply_human_review  # noqa: E402


DEMO_TEXT = """这次调整非常合理，给企业带来了新机会
政策落地后成本下降了，确实是个好消息
一天一个变化，完全是在折腾普通消费者
呵呵，真是太贴心了，又让普通人多花钱
这事跟我没关系"""
DEMO_CONTEXT = "某项关税政策频繁调整，引发对消费者成本、企业机会和政策稳定性的讨论。"
DEMO_TARGET = "判断评论对关税政策调整及其影响的立场"
REVIEW_HEADERS = [
    "样本编号",
    "评论",
    "XGBoost",
    "XGB置信度",
    "辅助模型标签",
    "升级原因",
    "Qwen标签",
    "Qwen置信度",
    "Qwen理由",
    "最终标签",
    "决策路径",
    "人工最终标签",
]


def _markdown_evidence(result: dict[str, Any]) -> str:
    evidence = result.get("retrieved_evidence") or []
    if not evidence:
        return "### 检索证据\n\n未接受历史事件证据；系统不会用低相关内容补足结果。"

    rows = ["### 检索证据", "", "| 历史事件 | 相关分 | 证据编号 |", "|---|---:|---|"]
    for item in evidence:
        event_id = str(item.get("event_id", "-"))
        score = float(item.get("score") or 0)
        evidence_id = str(item.get("evidence_id", "-"))
        rows.append(f"| {event_id} | {score:.4f} | `{evidence_id}` |")
    rows.extend(["", "> 公开 Demo 使用合成事件卡；检索结果提供上下文，不证明因果关系。"])
    return "\n".join(rows)


def _markdown_risk(result: dict[str, Any]) -> str:
    report = result.get("analysis_report") or {}
    signals = report.get("risk_signals") or ["无"]
    actions = report.get("recommended_actions") or ["无"]
    attention = str(report.get("attention_level", "Uncertain"))
    attention_labels = {"Low": "低", "Medium": "中", "High": "高", "Uncertain": "待复核"}
    snapshot = report.get("sentiment_snapshot") or {}
    proportions = snapshot.get("proportions") or {}
    negative_share = float(proportions.get("Negative") or 0)
    disagreement_rate = float(snapshot.get("model_disagreement_rate") or 0)
    summary = (
        f"事件 {report.get('event_id', '未命名事件')} 共分析 {snapshot.get('total', 0)} 条评论；"
        f"负面占比 {negative_share:.1%}，模型分歧率 {disagreement_rate:.1%}。"
    )
    return "\n".join(
        [
            "### 风险结论",
            "",
            f"**关注级别：{attention_labels.get(attention, attention)}**",
            "",
            summary,
            "",
            "**风险信号**",
            *[f"- {item}" for item in signals],
            "",
            "**建议动作**",
            *[f"- {item}" for item in actions],
        ]
    )


def _markdown_review(result: dict[str, Any]) -> str:
    report = result.get("analysis_report") or {}
    decision = result.get("route_decision") or {}
    status = str(report.get("review_status") or "unknown")
    status_labels = {
        "manual_required": "需要人工复核",
        "human_completed": "人工复核已完成",
        "llm_completed": "LLM 复核已完成",
        "llm_failed": "LLM 复核失败，已降级为人工接管",
        "not_required": "当前策略允许自动放行",
        "baseline_ready": "当前策略允许自动放行",
    }
    reasons = decision.get("reasons") or ["未触发额外复核条件"]
    reviewer_name = str((result.get("review_result") or {}).get("reviewer", "未调用"))
    if all(os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")):
        reviewer_state = f"在线 Reviewer：{reviewer_name}"
    elif reviewer_name == "offline_demo_replay_v1":
        reviewer_state = "离线验收回放（预置样例）与人工兜底"
    else:
        reviewer_state = "未配置在线 Reviewer（人工复核降级）"
    return "\n".join(
        [
            "### 复核状态",
            "",
            f"**{status_labels.get(status, status)}**",
            "",
            f"- 路由原因：{'；'.join(map(str, reasons))}",
            f"- 策略版本：{decision.get('policy_version', '未记录')}",
            f"- Reviewer：{reviewer_state}",
            "- 未完成人工或 LLM 复核的争议评论不得作为最终业务结论。",
        ]
    )


def _review_table(result: dict[str, Any]) -> list[list[Any]]:
    route_by_id = {
        str(item.get("sample_id")): item
        for item in (result.get("route_decision") or {}).get("items", [])
    }
    return [
        [
            item.get("sample_id", ""),
            item.get("text", ""),
            item.get("original_label", item.get("label", "")),
            round(float(item.get("confidence") or 0), 3),
            item.get("secondary_label", "-"),
            "；".join(
                item.get("review_reasons")
                or route_by_id.get(str(item.get("sample_id")), {}).get("reasons", [])
            ) or "未升级",
            item.get("qwen_label", "-"),
            item.get("qwen_confidence", "-"),
            item.get("qwen_rationale", "-"),
            (
                "待人工确认"
                if item.get("decision_path") == "manual_required"
                else item.get("label", "")
            ),
            item.get(
                "decision_path",
                route_by_id.get(str(item.get("sample_id")), {}).get(
                    "decision_path", "fast_path"
                ),
            ),
            item.get("label", ""),
        ]
        for item in result.get("sentiment_results") or []
    ]


def analyze(
    event_id: str,
    query: str,
    event_target: str,
    source_post: str,
    comments_text: str,
) -> tuple[str, str, str, str, list[list[Any]], str]:
    comments = [line.strip() for line in comments_text.splitlines() if line.strip()]
    if not comments:
        raise gr.Error("请至少输入一条舆情评论，每行一条。")
    if len(comments) > 100:
        raise gr.Error("公开 Demo 单次最多处理 100 条评论。")
    if not event_target.strip():
        raise gr.Error("请填写事件研判目标，避免脱离目标判断情绪。")
    if not source_post.strip():
        raise gr.Error("请填写原帖或事件背景，短文本必须结合上下文判断。")

    context = (
        f"事件目标：{event_target.strip()}\n"
        f"原帖/事件背景：{source_post.strip()}"
    )

    state = {
        "request_id": str(uuid.uuid4()),
        "event_id": (event_id or "未命名事件").strip(),
        "query": (query or "分析舆情风险并检索历史证据").strip(),
        "comments": [
            {
                "sample_id": f"comment-{index}",
                "text": text,
                "context": context,
            }
            for index, text in enumerate(comments, start=1)
        ],
        "tool_traces": [],
        "errors": [],
    }
    result = get_default_graph().invoke(state)
    return (
        _markdown_evidence(result),
        _markdown_risk(result),
        _markdown_review(result),
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        _review_table(result),
        json.dumps(result, ensure_ascii=False, default=str),
    )


def apply_review_ui(
    review_rows: list[list[Any]],
    state_json: str,
) -> tuple[str, str, str, list[list[Any]], str]:
    if not state_json:
        raise gr.Error("请先运行研判，再提交人工复核。")
    if not review_rows:
        raise gr.Error("没有可复核的评论。")
    final_labels = {}
    for row in review_rows:
        if len(row) < 12:
            raise gr.Error("复核表结构不完整，请重新运行研判。")
        final_labels[str(row[0])] = str(row[11]).strip()
    try:
        state = json.loads(state_json)
        update = apply_human_review(state, final_labels)
    except (ValueError, json.JSONDecodeError) as exc:
        raise gr.Error(str(exc)) from exc
    result = {**state, **update}
    result["tool_traces"] = [
        *(state.get("tool_traces") or []),
        *(update.get("tool_traces") or []),
    ]
    serialized = json.dumps(result, ensure_ascii=False, default=str)
    return (
        _markdown_risk(result),
        _markdown_review(result),
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        _review_table(result),
        serialized,
    )


def load_example() -> tuple[str, str, str, str, str]:
    return (
        "关税政策调整",
        "分析政策调整相关评论，识别争议内容并检索可参考的历史事件",
        DEMO_TARGET,
        DEMO_CONTEXT,
        DEMO_TEXT,
    )


with gr.Blocks(title="可复核中文舆情风险研判 Agent") as demo:
    gr.Markdown(
        """
        # 可复核中文舆情风险研判 Agent
        输入舆情评论后，工作流会展示 **XGBoost 快速判断 → 分歧/低置信/短文本路由 → 事件感知 Qwen 复核 → 人工兜底**。
        公开模式仅使用合成事件卡。未配置 LLM Key 时，预置样例会同时展示
        **XGBoost 快速放行、离线验收回放和人工兜底**；自由输入不会伪造在线模型结果。
        """
    )
    with gr.Row():
        with gr.Column(scale=2):
            event_id = gr.Textbox(label="事件名称", value="关税政策调整")
            query = gr.Textbox(
                label="研判任务",
                value="分析政策调整相关评论，识别争议内容并检索可参考的历史事件",
            )
            event_target = gr.Textbox(
                label="事件研判目标（Reviewer 判断评论相对于谁/什么的立场）",
                value=DEMO_TARGET,
                lines=2,
            )
            source_post = gr.Textbox(
                label="原帖/事件背景（Reviewer 用于解析指代、反讽和短回复）",
                value=DEMO_CONTEXT,
                lines=3,
            )
            comments = gr.Textbox(
                label="舆情评论（每行一条）", value=DEMO_TEXT, lines=9
            )
            with gr.Row():
                example_button = gr.Button("加载示例")
                run_button = gr.Button("运行研判", variant="primary")
        with gr.Column(scale=3):
            evidence_output = gr.Markdown("### 检索证据\n\n运行后显示。")
            risk_output = gr.Markdown("### 风险结论\n\n运行后显示。")
            review_output = gr.Markdown("### 复核状态\n\n运行后显示。")

    gr.Markdown(
        "### 人工复核工作台\n"
        "表格逐条展示升级原因、Qwen 结果和最终路径；需要人工兜底时，只修改最后一列。"
    )
    review_table = gr.Dataframe(
        headers=REVIEW_HEADERS,
        datatype=[
            "str", "str", "str", "number", "str", "str",
            "str", "str", "str", "str", "str", "str",
        ],
        column_count=(12, "fixed"),
        type="array",
        interactive=True,
        wrap=True,
    )
    apply_review_button = gr.Button("应用人工复核并重新生成简报", variant="secondary")
    analysis_state = gr.State("")

    with gr.Accordion("查看完整审计 JSON", open=False):
        audit_output = gr.Code(label="Audit JSON", language="json")

    example_button.click(
        load_example,
        outputs=[event_id, query, event_target, source_post, comments],
    )
    run_button.click(
        analyze,
        inputs=[event_id, query, event_target, source_post, comments],
        outputs=[
            evidence_output,
            risk_output,
            review_output,
            audit_output,
            review_table,
            analysis_state,
        ],
    )
    apply_review_button.click(
        apply_review_ui,
        inputs=[review_table, analysis_state],
        outputs=[
            risk_output,
            review_output,
            audit_output,
            review_table,
            analysis_state,
        ],
    )


if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=True,
    )
