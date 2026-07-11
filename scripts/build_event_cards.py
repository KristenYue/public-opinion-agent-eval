from argparse import ArgumentParser
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.retrieval import build_event_cards  # noqa: E402


def main() -> None:
    parser = ArgumentParser(description="Build one retrieval card per event")
    parser.add_argument("--raw-events-dir", type=Path, required=True)
    parser.add_argument(
        "--comments",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "comments_deduplicated.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "event_cards.jsonl",
    )
    args = parser.parse_args()

    comments = pd.read_csv(args.comments)
    event_ids = sorted(comments["event_id"].dropna().astype(str).unique().tolist())
    cards = build_event_cards(args.raw_events_dir, event_ids, args.output)
    print(f"Built {len(cards)} event cards at {args.output}")


if __name__ == "__main__":
    main()
