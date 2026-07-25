"""从训练事件的未标注评论池生成主动学习二次标注队列。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import argparse
import json
import math
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402
from opinion_agent.sentiment.preprocessing import clean_text  # noqa: E402


LABELS = {"Negative", "Neutral", "Positive"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_post_context_lookup(raw_events_dir: Path) -> dict[tuple[str, str], str]:
    """按 source_file + 评论正文恢复它实际回复的原帖正文。"""
    lookup: dict[tuple[str, str], str] = {}
    for comments_path in sorted(raw_events_dir.glob("*_comments*.csv")):
        posts_name = comments_path.name.replace("_comments", "_posts")
        posts_path = comments_path.with_name(posts_name)
        if not posts_path.exists():
            continue
        comments = pd.read_csv(comments_path, dtype=str).fillna("")
        posts = pd.read_csv(posts_path, dtype=str).fillna("")
        if not {"weibo_id", "content"}.issubset(comments.columns):
            continue
        if not {"mid", "content"}.issubset(posts.columns):
            continue
        post_by_id = {
            str(row["mid"]): str(row["content"]).strip()
            for _, row in posts.iterrows()
            if str(row["content"]).strip()
        }
        for _, row in comments.iterrows():
            comment = str(row["content"]).strip()
            post = post_by_id.get(str(row["weibo_id"]), "")
            if comment and post:
                lookup.setdefault((comments_path.name, comment), post)
    return lookup


def priority_score(row: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    xgb_label = str(row["xgb_suggestion"])
    snow_label = str(row["snownlp_suggestion"])
    xgb_confidence = float(row["xgb_confidence"])
    snow_score = float(row["snownlp_score"])
    score = 1.0 - xgb_confidence
    if xgb_label != snow_label:
        score += 1.5
        reasons.append("model_disagreement")
    negative_signal = max(
        float(row.get("xgb_negative_probability", 0.0)),
        1.0 - snow_score,
    )
    score += 1.25 * negative_signal
    if negative_signal >= 0.65:
        reasons.append("negative_candidate")
    length = len(str(row["content"]).strip())
    if length <= 10:
        score += 0.4
        reasons.append("short_text_context_risk")
    engagement = max(0.0, float(row.get("like_count", 0) or 0)) + max(
        0.0, float(row.get("reply_count", 0) or 0)
    )
    score += min(math.log1p(engagement) / 20.0, 0.3)
    if engagement >= 10:
        reasons.append("high_engagement")
    if not reasons:
        reasons.append("low_confidence")
    return score, reasons


def select_event_balanced(
    scored_rows: list[dict[str, Any]], *, target_size: int
) -> list[dict[str, Any]]:
    if target_size <= 0:
        raise ValueError("target_size 必须大于 0")
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in scored_rows:
        by_event.setdefault(str(row["event_id"]), []).append(row)
    if not by_event:
        return []
    for rows in by_event.values():
        rows.sort(key=lambda item: (-float(item["selection_score"]), str(item["sample_id"])))

    quota = max(1, target_size // len(by_event))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for event_id in sorted(by_event):
        for row in by_event[event_id][:quota]:
            selected.append(row)
            selected_ids.add(str(row["sample_id"]))
    if len(selected) < target_size:
        remainder = sorted(
            (row for row in scored_rows if str(row["sample_id"]) not in selected_ids),
            key=lambda item: (-float(item["selection_score"]), str(item["sample_id"])),
        )
        selected.extend(remainder[: target_size - len(selected)])
    return selected[:target_size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--comments",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "comments_deduplicated.csv",
    )
    parser.add_argument("--gold-data", type=Path, required=True)
    parser.add_argument(
        "--raw-events-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw_private" / "events",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "legacy_baseline",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=240)
    args = parser.parse_args()

    gold_rows = read_jsonl(args.gold_data)
    train_events = {
        str(row["event_id"]) for row in gold_rows if row.get("split") == "train"
    }
    frozen_events = {
        str(row["event_id"])
        for row in gold_rows
        if row.get("split") in {"validation", "test"}
    }
    known_ids = {str(row["sample_id"]) for row in gold_rows}
    comments = pd.read_csv(args.comments).fillna("")
    pool = comments[
        comments["event_id"].astype(str).isin(train_events)
        & ~comments["sample_id"].astype(str).isin(known_ids)
    ].copy()
    before_scorable_filter = len(pool)
    pool = pool[pool["content"].map(lambda value: bool(clean_text(str(value))))].copy()
    unscorable_excluded = before_scorable_filter - len(pool)
    if pool.empty:
        raise ValueError("训练事件的未标注池为空")
    if set(pool["event_id"].astype(str)) & frozen_events:
        raise AssertionError("主动学习池混入冻结的验证或测试事件")

    classifier = SentimentClassifier(args.artifacts_dir)
    secondary = SnowNLPSentimentClassifier()
    texts = pool["content"].astype(str).tolist()
    xgb_predictions = classifier.predict_many(texts)
    snow_predictions = [secondary.predict(text) for text in texts]
    context_lookup = build_post_context_lookup(args.raw_events_dir)

    scored: list[dict[str, Any]] = []
    for (_, row), xgb, snow in zip(pool.iterrows(), xgb_predictions, snow_predictions):
        source_file = str(row.get("source_file", ""))
        content = str(row["content"]).strip()
        item = {
            "sample_id": str(row["sample_id"]),
            "event_id": str(row["event_id"]),
            "split": "train",
            "post_text": context_lookup.get((source_file, content), ""),
            "content": content,
            "provisional_label": xgb.label if xgb.label in LABELS else "Neutral",
            "provisional_confidence": "Low",
            "xgb_suggestion": xgb.label,
            "xgb_confidence": xgb.confidence,
            "xgb_negative_probability": xgb.probabilities.get("Negative", 0.0),
            "snownlp_suggestion": snow.label,
            "snownlp_score": snow.score,
            "review_priority": "High",
            "like_count": int(float(row.get("like_count", 0) or 0)),
            "reply_count": int(float(row.get("reply_count", 0) or 0)),
            "previous_notes": "",
        }
        score, reasons = priority_score(item)
        item["selection_score"] = round(score, 6)
        item["selection_reason"] = reasons
        if not item["post_text"]:
            item["selection_reason"].append("missing_exact_post_context")
        scored.append(item)

    selected = select_event_balanced(scored, target_size=min(args.size, len(scored)))
    write_jsonl(args.output, selected)
    report = {
        "output": str(args.output),
        "selected": len(selected),
        "pool": len(pool),
        "unscorable_excluded": unscorable_excluded,
        "train_events": sorted(train_events),
        "frozen_events_excluded": sorted(frozen_events),
        "selected_event_counts": dict(Counter(row["event_id"] for row in selected)),
        "xgb_label_counts": dict(Counter(row["xgb_suggestion"] for row in selected)),
        "snownlp_label_counts": dict(Counter(row["snownlp_suggestion"] for row in selected)),
        "exact_context_coverage": sum(bool(row["post_text"]) for row in selected) / len(selected),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
