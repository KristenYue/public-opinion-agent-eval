"""Compare sparse and dense event-card retrieval on a reproducible sanity set."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.retrieval import (  # noqa: E402
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)


QUERIES = {
    "北京大风": "北京出现大风天气预警，市民讨论出行安全和树木倒伏",
    "北京交通大学": "北京交通大学校园相关讨论和学校生活",
    "关税": "中美关税和进口商品税率调整引发讨论",
    "雷军": "雷军和小米相关网络舆论",
    "天蝎座": "星座运势与天蝎座好运讨论",
    "万千气象看江苏": "江苏文旅和地方文化景点宣传",
    "五一反向旅游": "五一假期反向旅游和冷门目的地选择",
    "五月天演唱会": "五月天演唱会现场和歌迷评价",
    "武汉樱花": "武汉赏樱和樱花季旅游",
    "延迟法定退休年龄改革": "延迟退休政策和法定退休年龄改革",
    "一生爱凑热闹的中国人": "中国人爱凑热闹和围观活动",
    "云南广西要热到40度了": "云南广西高温天气接近四十度",
}


def evaluate(name: str, retriever) -> dict[str, object]:
    hits_at_1 = 0
    reciprocal_ranks: list[float] = []
    failures: list[dict[str, object]] = []
    top1_misses: list[dict[str, object]] = []
    for expected, query in QUERIES.items():
        results = retriever.retrieve(query, top_k=5)
        ranked = [item["event_id"] for item in results]
        if ranked and ranked[0] == expected:
            hits_at_1 += 1
        else:
            top1_misses.append({"expected": expected, "query": query, "ranked": ranked})
        try:
            rank = ranked.index(expected) + 1
            reciprocal_ranks.append(1 / rank)
        except ValueError:
            reciprocal_ranks.append(0.0)
            failures.append({"expected": expected, "query": query, "ranked": ranked})
    return {
        "retriever": name,
        "queries": len(QUERIES),
        "recall_at_1": hits_at_1 / len(QUERIES),
        "mrr_at_5": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "top1_misses": top1_misses,
        "failures": failures,
    }


def main() -> None:
    cards = PROJECT_ROOT / "data" / "processed" / "event_cards.jsonl"
    output = PROJECT_ROOT / "data" / "processed" / "retrieval_baseline_metrics.json"
    sparse = TfidfEventRetriever(cards)
    dense = SemanticEventRetriever(cards)
    hybrid = HybridEventRetriever(sparse, dense, min_dense_score=None)
    report = {
        "dataset": "12 manually written event-title queries; sanity benchmark only",
        "results": [
            evaluate("tfidf_char_ngram", sparse),
            evaluate(dense.model_name, dense),
            evaluate("hybrid_rrf", hybrid),
        ],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
