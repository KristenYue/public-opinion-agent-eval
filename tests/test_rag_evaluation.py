from opinion_agent.evaluation.rag import evaluate_rag


class StubRetriever:
    def __init__(self) -> None:
        self.last_rejections = []

    def retrieve(self, query: str, top_k: int = 5):
        self.last_rejections = []
        if query == "positive":
            return [{"event_id": "relevant"}, {"event_id": "other"}]
        if query == "injection":
            self.last_rejections = [{"event_id": "poison", "reasons": ["rule"]}]
        return []


def test_rag_metrics_cover_relevance_abstention_and_injection() -> None:
    dataset = {
        "schema_version": "test",
        "queries": [
            {
                "id": "p",
                "category": "positive",
                "query": "positive",
                "relevant_event_ids": ["relevant"],
            },
            {
                "id": "n",
                "category": "irrelevant",
                "query": "negative",
                "relevant_event_ids": [],
            },
            {
                "id": "s",
                "category": "prompt_injection",
                "query": "injection",
                "relevant_event_ids": [],
                "prohibited_event_ids": ["poison"],
            },
        ],
        "gates": {
            "recall_at_5": 1.0,
            "mrr_at_5": 1.0,
            "ndcg_at_5": 1.0,
            "top1_citation_accuracy": 1.0,
            "irrelevant_rejection_rate": 1.0,
            "prompt_injection_rejection_rate": 1.0,
            "positive_evidence_rate": 1.0,
        },
    }

    result = evaluate_rag(StubRetriever(), dataset)

    assert result["status"] == "passed"
    assert all(value == 1.0 for value in result["metrics"].values())
    assert result["bad_cases"] == []
