"""Stable tokenizer module required by the serialized TF-IDF vectorizer."""

import jieba


def jieba_tokenizer(text: str) -> list[str]:
    return jieba.lcut(text)
