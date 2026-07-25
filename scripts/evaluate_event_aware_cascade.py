"""Evaluate the event-aware cascade on fully annotated, event-isolated rows.

The script deliberately refuses to emit metrics until every selected queue row
has a human label and every Qwen-routed row has a saved reviewer response.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import argparse
import json
import sys

from sklearn.metrics import accuracy_score, f1_score, recall_score


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
MODEL_ROOT = WORKSPACE_ROOT / "本科毕设_情感分析_恢复版"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.sentiment import (  # noqa: E402
    SentimentClassifier,
    SnowNLPSentimentClassifier,
)


LABELS = ["Negative", "Neutral", "Positive", "Unscorable"]
LABEL_NORMALIZATION = {"Exclude": "Unscorable", "Unscorable": "Unscorable"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_label(value: object) -> str:
    label = LABEL_NORMALIZATION.get(str(value), str(value))
    if label not in LABELS:
        raise ValueError(f"Unsupported label: {value}")
    return label


def assert_event_isolation(queue: list[dict[str, Any]]) -> dict[str, str]:
    event_splits: dict[str, set[str]] = {}
    for row in queue:
        event_splits.setdefault(str(row["event_id"]), set()).add(str(row["split"]))
    leaking = {event: sorted(splits) for event, splits in event_splits.items() if len(splits) != 1}
    if leaking:
        raise ValueError(f"Event isolation violated: {leaking}")
    return {event: next(iter(splits)) for event, splits in event_splits.items()}


def classification_metrics(truth: list[str], predicted: list[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1": float(
            f1_score(truth, predicted, labels=LABELS, average="macro", zero_division=0)
        ),
        "negative_recall": float(
            recall_score(
                truth,
                predicted,
                labels=["Negative"],
                average="macro",
                zero_division=0,
            )
        ),
    }
    recalls = recall_score(
        truth,
        predicted,
        labels=LABELS,
        average=None,
        zero_division=0,
    )
    metrics["per_class_recall"] = {
        label: float(score) for label, score in zip(LABELS, recalls, strict=True)
    }
    return metrics


def evaluate_cascade(
    rows: list[dict[str, Any]],
    qwen: dict[str, dict[str, Any]],
    *,
    threshold: float,
    short_text_max_chars: int,
    route_mode: str = "event_aware",
    human_fallback: bool = True,
) -> dict[str, Any]:
    truth = [str(row["gold"]) for row in rows]
    automated: list[str] = []
    operational: list[str] = []
    auto_truth: list[str] = []
    auto_pred: list[str] = []
    routed = human = corrected = harmful = 0
    missing_qwen: list[str] = []
    for row in rows:
        disagreement = row["xgb_label"] != row["secondary_label"]
        if route_mode == "disagreement_only":
            needs_qwen = disagreement
        else:
            needs_qwen = (
                disagreement
                or float(row["xgb_confidence"]) < threshold
                or len(str(row["content"]).strip()) <= short_text_max_chars
            )
        if not needs_qwen:
            chosen = str(row["xgb_label"])
            automated.append(chosen)
            operational.append(chosen)
            auto_truth.append(str(row["gold"]))
            auto_pred.append(chosen)
            continue
        routed += 1
        response = qwen.get(str(row["sample_id"]))
        if response is None:
            missing_qwen.append(str(row["sample_id"]))
            continue
        qwen_label = normalize_label(response["label"])
        high_confidence = str(response.get("confidence")) == "High"
        automated_choice = qwen_label if high_confidence else str(row["xgb_label"])
        automated.append(automated_choice)
        if high_confidence:
            operational_choice = qwen_label
            corrected += row["xgb_label"] != row["gold"] and qwen_label == row["gold"]
            harmful += row["xgb_label"] == row["gold"] and qwen_label != row["gold"]
            auto_truth.append(str(row["gold"]))
            auto_pred.append(qwen_label)
        elif human_fallback:
            operational_choice = str(row["gold"])
            human += 1
        else:
            operational_choice = automated_choice
            auto_truth.append(str(row["gold"]))
            auto_pred.append(automated_choice)
        operational.append(operational_choice)
    if missing_qwen:
        raise ValueError(
            f"Missing Qwen responses for {len(missing_qwen)} routed rows"
        )
    automated_metrics = classification_metrics(truth, automated)
    operational_metrics = classification_metrics(truth, operational)
    selective_metrics = (
        classification_metrics(auto_truth, auto_pred)
        if auto_truth
        else {"accuracy": 0.0, "macro_f1": 0.0, "negative_recall": 0.0}
    )
    return {
        "confidence_threshold": threshold,
        **operational_metrics,
        "automated_metrics_without_human": automated_metrics,
        "selective_auto_metrics": selective_metrics,
        "qwen_route_rate": routed / len(rows) if rows else 0.0,
        "human_intervention_rate": human / len(rows) if rows else 0.0,
        "auto_processing_rate": 1.0 - (human / len(rows) if rows else 0.0),
        "qwen_corrected_errors": corrected,
        "qwen_harmful_overrides": harmful,
    }


def select_threshold(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Select on validation only: Macro-F1, accuracy, then automation."""
    if not points:
        raise ValueError("No validation threshold points")
    return max(
        points,
        key=lambda point: (
            float(point["macro_f1"]),
            float(point["accuracy"]),
            float(point["auto_processing_rate"]),
        ),
    )


def write_tradeoff_svg(path: Path, points: list[dict[str, Any]]) -> None:
    width, height, margin = 720, 440, 70
    plot_w, plot_h = width - 2 * margin, height - 2 * margin
    coords = []
    for point in points:
        x = margin + float(point["auto_processing_rate"]) * plot_w
        y = margin + (1.0 - float(point["accuracy"])) * plot_h
        coords.append((x, y, point))
    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#6d4aff"/>'
        f'<text x="{x + 10:.1f}" y="{y - 8:.1f}" font-size="13">'
        f'τ={point["confidence_threshold"]:.2f}</text>'
        for x, y, point in coords
    )
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in coords)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{width/2}" y="28" text-anchor="middle" font-size="20">准确率—自动处理率权衡</text>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#333"/>
<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#333"/>
<text x="{width/2}" y="{height-18}" text-anchor="middle">自动处理率</text>
<text x="18" y="{height/2}" transform="rotate(-90 18 {height/2})" text-anchor="middle">准确率</text>
<polyline points="{polyline}" fill="none" stroke="#6d4aff" stroke-width="2"/>
{circles}
</svg>'''
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queue",
        type=Path,
        default=MODEL_ROOT / "data" / "annotation_workbench" / "new_events_queue.jsonl",
    )
    parser.add_argument(
        "--reviews",
        type=Path,
        default=MODEL_ROOT / "data" / "annotation_workbench" / "new_events_reviews.jsonl",
    )
    parser.add_argument(
        "--qwen-responses",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "event_aware_qwen_responses_v2.jsonl",
    )
    parser.add_argument(
        "--split",
        choices=["protocol", "validation", "test"],
        default="protocol",
        help="protocol selects the threshold on validation and evaluates test once",
    )
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.50, 0.65, 0.80])
    parser.add_argument("--short-text-max-chars", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "event_aware_cascade_metrics.json",
    )
    args = parser.parse_args()

    queue = read_jsonl(args.queue)
    if not queue:
        raise SystemExit(f"BLOCKED: annotation queue is missing or empty: {args.queue}")
    event_splits = assert_event_isolation(queue)
    reviews = {str(row["sample_id"]): row for row in read_jsonl(args.reviews)}
    missing_reviews = [str(row["sample_id"]) for row in queue if str(row["sample_id"]) not in reviews]
    if missing_reviews:
        raise SystemExit(
            f"BLOCKED: human annotation incomplete: {len(reviews)}/{len(queue)} complete; "
            f"missing={len(missing_reviews)}. No metrics were produced."
        )

    xgb = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    snow = SnowNLPSentimentClassifier()
    qwen = {str(row["sample_id"]): row for row in read_jsonl(args.qwen_responses)}
    evaluation_rows: dict[str, list[dict[str, Any]]] = {}
    for split in ("validation", "test"):
        rows = [dict(row) for row in queue if str(row["split"]) == split]
        for row in rows:
            review = reviews[str(row["sample_id"])]
            row["gold"] = normalize_label(review["human_label"])
            row["gold_needs_second_pass"] = bool(review.get("needs_review"))
            primary = xgb.predict(str(row["content"]))
            secondary = snow.predict(str(row["content"]))
            row["xgb_label"] = primary.label
            row["xgb_confidence"] = primary.confidence
            row["secondary_label"] = secondary.label
        evaluation_rows[split] = rows

    try:
        if args.split in {"validation", "test"}:
            rows = evaluation_rows[args.split]
            truth = [str(row["gold"]) for row in rows]
            points = [
                evaluate_cascade(
                    rows,
                    qwen,
                    threshold=threshold,
                    short_text_max_chars=args.short_text_max_chars,
                )
                for threshold in sorted(args.thresholds)
            ]
            report = {
                "truth_status": (
                    "provisional_second_pass_incomplete"
                    if any(row["gold_needs_second_pass"] for row in rows)
                    else "second_pass_adjudicated"
                ),
                "split": args.split,
                "event_isolation_verified": True,
                "event_splits": event_splits,
                "evaluation_events": sorted({str(row["event_id"]) for row in rows}),
                "samples": len(rows),
                "label_counts": dict(Counter(truth)),
                "xgboost_baseline": classification_metrics(
                    truth, [str(row["xgb_label"]) for row in rows]
                ),
                "threshold_points": points,
                "pending_second_pass": sum(
                    bool(row["gold_needs_second_pass"]) for row in rows
                ),
            }
            threshold_points = points
        else:
            validation_rows = evaluation_rows["validation"]
            test_rows = evaluation_rows["test"]
            validation_points = [
                evaluate_cascade(
                    validation_rows,
                    qwen,
                    threshold=threshold,
                    short_text_max_chars=args.short_text_max_chars,
                )
                for threshold in sorted(args.thresholds)
            ]
            selected = select_threshold(validation_points)
            locked_threshold = float(selected["confidence_threshold"])
            test_point = evaluate_cascade(
                test_rows,
                qwen,
                threshold=locked_threshold,
                short_text_max_chars=args.short_text_max_chars,
            )
            disagreement_only = evaluate_cascade(
                test_rows,
                qwen,
                threshold=locked_threshold,
                short_text_max_chars=args.short_text_max_chars,
                route_mode="disagreement_only",
                human_fallback=False,
            )
            automated_cascade = evaluate_cascade(
                test_rows,
                qwen,
                threshold=locked_threshold,
                short_text_max_chars=args.short_text_max_chars,
                human_fallback=False,
            )
            test_truth = [str(row["gold"]) for row in test_rows]
            baseline = classification_metrics(
                test_truth, [str(row["xgb_label"]) for row in test_rows]
            )
            pending = sum(
                bool(row["gold_needs_second_pass"])
                for row in validation_rows + test_rows
            )
            report = {
                "protocol": "event_isolated_validation_selected_v1",
                "truth_status": (
                    "provisional_second_pass_incomplete"
                    if pending
                    else "second_pass_adjudicated"
                ),
                "event_isolation_verified": True,
                "event_splits": event_splits,
                "validation_events": sorted(
                    {str(row["event_id"]) for row in validation_rows}
                ),
                "test_events": sorted({str(row["event_id"]) for row in test_rows}),
                "validation_samples": len(validation_rows),
                "test_samples": len(test_rows),
                "pending_second_pass": pending,
                "selection_rule": (
                    "maximize validation Macro-F1, then accuracy, then auto-processing rate"
                ),
                "validation_threshold_points": validation_points,
                "selected_threshold": locked_threshold,
                "locked_test_result": test_point,
                "test_xgboost_baseline": baseline,
                "ablation": [
                    {"stage": "xgboost_baseline", **baseline},
                    {
                        "stage": "plus_disagreement_routing_and_high_confidence_qwen",
                        **disagreement_only["automated_metrics_without_human"],
                        "qwen_route_rate": disagreement_only["qwen_route_rate"],
                        "human_intervention_rate": 0.0,
                    },
                    {
                        "stage": "plus_event_aware_routing_and_context_qwen",
                        **automated_cascade["automated_metrics_without_human"],
                        "qwen_route_rate": automated_cascade["qwen_route_rate"],
                        "human_intervention_rate": 0.0,
                    },
                    {
                        "stage": "plus_human_fallback_full_cascade",
                        "accuracy": test_point["accuracy"],
                        "macro_f1": test_point["macro_f1"],
                        "negative_recall": test_point["negative_recall"],
                        "per_class_recall": test_point["per_class_recall"],
                        "qwen_route_rate": test_point["qwen_route_rate"],
                        "human_intervention_rate": test_point[
                            "human_intervention_rate"
                        ],
                        "auto_processing_rate": test_point["auto_processing_rate"],
                    },
                ],
                "limitations": [
                    "Full-cascade accuracy includes gold labels for human-fallback rows; "
                    "automated_metrics_without_human is reported separately.",
                    "Test threshold is selected only from validation metrics.",
                    "Metrics remain provisional until every needs_review annotation "
                    "receives a valid second-pass adjudication.",
                ],
            }
            threshold_points = validation_points
    except ValueError as exc:
        raise SystemExit(f"BLOCKED: {exc}. No metrics were produced.") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_tradeoff_svg(args.output.with_suffix(".svg"), threshold_points)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
