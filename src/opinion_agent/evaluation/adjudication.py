"""Build adjudication queues for provisional human labels."""

from collections import Counter
from collections.abc import Sequence

from .baselines import normalize_prediction


SHORT_TEXT_MAX_CHARS = 4
UNSCORABLE_LABEL = "Unscorable"


def adjudication_reasons(row: dict[str, object]) -> list[str]:
    """Return concrete reasons why a provisional label should be reviewed."""
    content = str(row.get("content") or "").strip()
    human_label = str(row.get("human_label") or "").strip()
    human_confidence = str(row.get("human_confidence") or "").strip()
    notes = str(row.get("notes") or "").strip()
    xgb = normalize_prediction(row.get("xgb_suggestion"))
    snow = normalize_prediction(row.get("snownlp_suggestion"))
    both_models_disagree = xgb != human_label and snow != human_label
    models_agree_against_label = xgb == snow and xgb != human_label
    unscorable_kept_as_sentiment = (
        str(row.get("xgb_suggestion") or "").strip() == UNSCORABLE_LABEL
        and human_label != "Exclude"
    )

    reasons: list[str] = []
    if len(content) <= SHORT_TEXT_MAX_CHARS:
        reasons.append("short_text")
    if human_confidence != "High":
        reasons.append("low_or_missing_human_confidence")
    if both_models_disagree:
        reasons.append("both_models_disagree_with_label")
    if models_agree_against_label:
        reasons.append("models_agree_against_label")
    if not notes and (
        human_confidence == "High"
        and (
            len(content) <= SHORT_TEXT_MAX_CHARS
            or both_models_disagree
            or unscorable_kept_as_sentiment
        )
    ):
        reasons.append("high_confidence_without_note")
    if unscorable_kept_as_sentiment:
        reasons.append("unscorable_model_output_kept_as_sentiment")
    return reasons


def adjudication_priority(reasons: Sequence[str]) -> str:
    severe = {
        "models_agree_against_label",
        "both_models_disagree_with_label",
        "unscorable_model_output_kept_as_sentiment",
    }
    if any(reason in severe for reason in reasons):
        return "High"
    if "short_text" in reasons or "low_or_missing_human_confidence" in reasons:
        return "Medium"
    return "Low"


def build_adjudication_queue(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    queue: list[dict[str, object]] = []
    for row in rows:
        reasons = adjudication_reasons(row)
        if not reasons:
            continue
        queue.append(
            {
                "sample_id": row.get("sample_id"),
                "event_id": row.get("event_id"),
                "content": row.get("content"),
                "post_text": row.get("post_text"),
                "post_url": row.get("post_url"),
                "human_label": row.get("human_label"),
                "human_confidence": row.get("human_confidence"),
                "notes": row.get("notes"),
                "xgb_suggestion": row.get("xgb_suggestion"),
                "xgb_confidence": row.get("xgb_confidence"),
                "snownlp_suggestion": row.get("snownlp_suggestion"),
                "snownlp_score": row.get("snownlp_score"),
                "adjudication_priority": adjudication_priority(reasons),
                "adjudication_reasons": reasons,
            }
        )
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    queue.sort(
        key=lambda item: (
            priority_rank[str(item["adjudication_priority"])],
            str(item["event_id"]),
            str(item["sample_id"]),
        )
    )
    return queue


def summarize_adjudication_queue(
    rows: Sequence[dict[str, object]],
    queue: Sequence[dict[str, object]],
) -> dict[str, object]:
    priority_counts = Counter(str(row["adjudication_priority"]) for row in queue)
    reason_counts = Counter(
        reason
        for row in queue
        for reason in row.get("adjudication_reasons", [])
    )
    event_counts = Counter(str(row["event_id"]) for row in queue)
    return {
        "truth_status": "provisional_single_annotator",
        "source_samples": len(rows),
        "adjudication_candidates": len(queue),
        "adjudication_rate": len(queue) / len(rows) if rows else 0.0,
        "priority_counts": dict(sorted(priority_counts.items())),
        "reason_counts": dict(reason_counts.most_common()),
        "event_counts": dict(sorted(event_counts.items())),
    }
