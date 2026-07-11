"""原始微博评论的只读审计、脱敏和去重逻辑。"""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re

import pandas as pd


_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION = re.compile(r"@[\w\-\u4e00-\u9fff]+")
_WHITESPACE = re.compile(r"\s+")
_COMMENTS_SUFFIX = re.compile(r"_comments(?:_\d+)?$", re.IGNORECASE)

PUBLIC_COLUMNS = [
    "sample_id",
    "event_id",
    "content",
    "normalized_text",
    "created_at",
    "like_count",
    "reply_count",
    "source_file",
]


@dataclass(frozen=True)
class AuditResult:
    files_seen: int
    files_used: int
    rows_read: int
    rows_with_text: int
    duplicate_rows_removed: int
    unique_rows: int
    events: int
    event_counts: dict[str, int]
    skipped_files: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_text(text: object) -> str:
    if text is None or pd.isna(text):
        return ""
    value = str(text).strip()
    value = _URL.sub("[URL]", value)
    value = _MENTION.sub("[MENTION]", value)
    return _WHITESPACE.sub(" ", value).strip()


def event_name_from_path(path: Path) -> str:
    return _COMMENTS_SUFFIX.sub("", path.stem).strip("_ ") or "unknown_event"


def _first_existing(frame: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series:
    for column in candidates:
        if column in frame.columns:
            return frame[column]
    return pd.Series([None] * len(frame), index=frame.index, dtype="object")


def audit_comment_files(raw_dir: Path) -> tuple[pd.DataFrame, AuditResult]:
    """读取`*_comments*.csv`，返回脱敏去重数据，不修改原文件。"""
    paths = sorted(raw_dir.glob("*_comments*.csv"))
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    rows_read = 0

    for path in paths:
        try:
            frame = pd.read_csv(path)
        except Exception:
            skipped.append(path.name)
            continue
        rows_read += len(frame)
        if frame.empty or "content" not in frame.columns:
            skipped.append(path.name)
            continue

        normalized = frame["content"].map(normalize_text)
        usable = normalized.ne("")
        selected = pd.DataFrame(index=frame.index[usable])
        selected["event_id"] = event_name_from_path(path)
        selected["content"] = frame.loc[usable, "content"].astype(str)
        selected["normalized_text"] = normalized[usable]
        selected["created_at"] = _first_existing(frame, ("created_at", "crawl_time", "time"))[usable]
        selected["like_count"] = _first_existing(frame, ("like_count", "likes", "star"))[usable]
        selected["reply_count"] = _first_existing(frame, ("reply_count", "comments", "replies"))[usable]
        selected["source_file"] = path.name
        selected["sample_id"] = selected.apply(
            lambda row: sha256(
                f"{row['event_id']}|{row['normalized_text']}".encode("utf-8")
            ).hexdigest()[:16],
            axis=1,
        )
        frames.append(selected[PUBLIC_COLUMNS])

    if not frames:
        empty = pd.DataFrame(columns=PUBLIC_COLUMNS)
        return empty, AuditResult(len(paths), 0, rows_read, 0, 0, 0, 0, {}, skipped)

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    # 全局按规范化文本去重，避免同一评论跨事件泄漏。
    deduplicated = combined.drop_duplicates(subset=["normalized_text"], keep="first").reset_index(drop=True)
    counts = deduplicated["event_id"].value_counts().sort_index().to_dict()
    result = AuditResult(
        files_seen=len(paths),
        files_used=len(frames),
        rows_read=rows_read,
        rows_with_text=before,
        duplicate_rows_removed=before - len(deduplicated),
        unique_rows=len(deduplicated),
        events=deduplicated["event_id"].nunique(),
        event_counts={str(key): int(value) for key, value in counts.items()},
        skipped_files=skipped,
    )
    return deduplicated, result
