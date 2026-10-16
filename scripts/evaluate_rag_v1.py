"""Run the frozen public synthetic RAG gate without network access."""

from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.rag import evaluate_rag, file_sha256, load_rag_evaluation  # noqa: E402
from opinion_agent.retrieval import GuardedRetriever, TfidfEventRetriever  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data/evaluation/rag_eval_v1.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data/evaluation/rag_eval_v1_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/evaluation/rag_eval_v1_metrics.json",
    )
    args = parser.parse_args()

    dataset = load_rag_evaluation(args.dataset)
    corpus = PROJECT_ROOT / str(dataset["corpus"])
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    actual_hashes = {
        "dataset_sha256": file_sha256(args.dataset),
        "corpus_sha256": file_sha256(corpus),
    }
    if actual_hashes != manifest.get("sha256"):
        raise SystemExit(
            "Frozen RAG inputs changed; create an explicit new dataset version instead of "
            "silently updating v1"
        )

    retriever = GuardedRetriever(TfidfEventRetriever(corpus, min_score=0.04))
    report = {
        **evaluate_rag(retriever, dataset, top_k=5),
        "dataset": str(args.dataset.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "corpus": str(corpus.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "sha256": actual_hashes,
        "retriever": "guarded_tfidf_char_ngrams_min_score_0.04",
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
