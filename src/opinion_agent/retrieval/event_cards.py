"""Build compact, auditable event cards from raw Weibo post exports."""

from pathlib import Path
import json

import pandas as pd


_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def mid_to_mblog_id(mid: str | int) -> str:
    """Convert a numeric Weibo MID to the public base62 post identifier."""
    value = str(mid).strip()
    if not value.isdigit():
        return value
    result: list[str] = []
    for end in range(len(value), 0, -7):
        start = max(0, end - 7)
        number = int(value[start:end])
        encoded = "0" if number == 0 else ""
        while number:
            number, remainder = divmod(number, 62)
            encoded = _BASE62[remainder] + encoded
        if start > 0:
            encoded = encoded.rjust(4, "0")
        result.append(encoded)
    return "".join(reversed(result))


def _as_int(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _source_url(uid: object, mid: object) -> str:
    uid_text = str(uid).strip()
    mid_text = str(mid).strip()
    if not uid_text or not mid_text or uid_text.lower() == "nan":
        return ""
    return f"https://weibo.com/{uid_text}/{mid_to_mblog_id(mid_text)}"


def build_event_cards(
    raw_events_dir: str | Path,
    event_ids: list[str],
    output_path: str | Path,
    representative_posts: int = 5,
) -> list[dict[str, object]]:
    """Create one event-level retrieval document per requested event."""
    raw_dir = Path(raw_events_dir)
    cards: list[dict[str, object]] = []

    for event_id in event_ids:
        path = raw_dir / f"{event_id}_posts.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing post file for event {event_id}: {path}")
        frame = pd.read_csv(path)
        if "content" not in frame.columns:
            raise ValueError(f"Post file has no content column: {path}")

        frame = frame.copy()
        frame["content"] = frame["content"].fillna("").astype(str).str.strip()
        frame = frame.loc[frame["content"] != ""].drop_duplicates(subset=["content"])
        for column in ("retweets", "comments", "likes"):
            frame[column] = frame[column].map(_as_int) if column in frame.columns else 0
        frame["engagement"] = frame["retweets"] + frame["comments"] + frame["likes"]
        frame = frame.sort_values(["engagement", "comments"], ascending=False)

        posts: list[dict[str, object]] = []
        for _, row in frame.head(representative_posts).iterrows():
            posts.append(
                {
                    "text": row["content"],
                    "post_time": str(row.get("post_time", "")),
                    "engagement": int(row["engagement"]),
                    "source_url": _source_url(row.get("uid", ""), row.get("mid", "")),
                }
            )

        cards.append(
            {
                "event_id": event_id,
                "title": event_id,
                "chunk_type": "event_card",
                "document": "\n".join(post["text"] for post in posts),
                "representative_posts": posts,
                "post_count": int(len(frame)),
                "source_file": path.name,
            }
        )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(json.dumps(card, ensure_ascii=False) + "\n")
    return cards
