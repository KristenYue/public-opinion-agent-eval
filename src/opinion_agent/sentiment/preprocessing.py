"""Text preprocessing compatible with the legacy TF-IDF vectorizer."""

import re


_NON_CHINESE_PATTERN = re.compile(r"[^\u4e00-\u9fa5，。！？]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_text(text: object) -> str:
    """Keep Chinese characters and common Chinese punctuation."""
    if text is None:
        return ""
    cleaned = _NON_CHINESE_PATTERN.sub("", str(text).strip())
    return _WHITESPACE_PATTERN.sub("", cleaned)
