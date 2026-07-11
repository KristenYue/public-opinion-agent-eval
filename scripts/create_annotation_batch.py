"""从多事件去重数据中均衡抽样，生成人工标注表。"""

from pathlib import Path
import argparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "processed" / "comments_deduplicated.csv")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "annotations" / "annotation_batch_001.csv")
    parser.add_argument("--size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data = pd.read_csv(args.input)
    if data.empty:
        raise ValueError("去重数据集为空")
    per_event = max(1, args.size // data["event_id"].nunique())
    sampled_groups = [
        group.sample(min(len(group), per_event), random_state=args.seed)
        for _, group in data.groupby("event_id", sort=True)
    ]
    sampled = pd.concat(sampled_groups, ignore_index=True)
    if len(sampled) < args.size:
        remaining = data[~data["sample_id"].isin(sampled["sample_id"])]
        extra = remaining.sample(min(args.size - len(sampled), len(remaining)), random_state=args.seed)
        sampled = pd.concat([sampled, extra], ignore_index=True)

    output = sampled[["sample_id", "event_id", "content", "source_file"]].copy()
    output["human_label"] = ""
    output["annotator_confidence"] = ""
    output["notes"] = ""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"已生成{len(output)}条人工标注任务: {args.output}")


if __name__ == "__main__":
    main()
