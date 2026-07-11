from pathlib import Path
import json
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.retrieval.event_cards import build_event_cards, mid_to_mblog_id  # noqa: E402


def test_build_event_cards_prefers_high_engagement_posts(tmp_path: Path) -> None:
    pd.DataFrame(
        [
            {"mid": "123", "uid": "42", "content": "普通帖子", "retweets": 1, "comments": 1, "likes": 1},
            {"mid": "456", "uid": "42", "content": "代表帖子", "retweets": 10, "comments": 10, "likes": 10},
        ]
    ).to_csv(tmp_path / "事件A_posts.csv", index=False)
    output = tmp_path / "cards.jsonl"

    cards = build_event_cards(tmp_path, ["事件A"], output, representative_posts=1)

    assert cards[0]["document"] == "代表帖子"
    persisted = json.loads(output.read_text(encoding="utf-8").strip())
    assert persisted["representative_posts"][0]["source_url"].startswith("https://weibo.com/42/")


def test_mid_conversion_is_stable() -> None:
    assert mid_to_mblog_id("0") == "0"
    assert mid_to_mblog_id("123")
