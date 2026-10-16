# Third-party notices

This repository contains original project code and uses third-party packages and a downloaded
embedding model at runtime. It does not claim authorship of those components. The links below are
the upstream sources used for the licensing audit on 2026-08-12.

| Component | How it is used | Upstream license/source |
|---|---|---|
| LangGraph | Agent graph orchestration | MIT — <https://github.com/langchain-ai/langgraph/blob/main/LICENSE> |
| BAAI/bge-small-zh-v1.5 | Dense retrieval model downloaded during image build | MIT — <https://huggingface.co/BAAI/bge-small-zh-v1.5> |
| SnowNLP | Secondary historical sentiment signal | MIT — <https://pypi.org/project/snownlp/> |
| sentence-transformers | BGE model runtime | Apache-2.0 — <https://github.com/huggingface/sentence-transformers/blob/main/LICENSE> |
| XGBoost | Runtime for the author-owned undergraduate baseline | Apache-2.0 — <https://github.com/dmlc/xgboost/blob/master/LICENSE> |
| scikit-learn | TF-IDF and model utilities | BSD-3-Clause — <https://github.com/scikit-learn/scikit-learn/blob/main/COPYING> |
| jieba | Chinese tokenization dependency | MIT — <https://github.com/fxsjy/jieba> |

Python packages are installed from `requirements.txt`; their source is not vendored into this
repository. BGE weights are downloaded from the named upstream repository during the Docker build
and are not committed here.

The three files under `artifacts/legacy_baseline/` were trained by the project author for an
undergraduate thesis. They are retained as reproducible research baselines and verified against
`artifacts/legacy_baseline/manifest.json`. They are not pretrained third-party model weights.

## Excluded legacy resources

Earlier commits carried BosonNLP/HowNet-style sentiment dictionaries, a stop-word list and a
negation list. No current code, evaluation or test used them, and their provenance did not include
verifiable redistribution terms. They have been removed from the current tree and are prohibited
by the release-readiness gate. Do not restore or redistribute them without documented permission.

## Repository license status

No root code license has been selected yet. Until the copyright owner explicitly selects one, the
absence of a license means no general permission is granted to copy, modify or redistribute the
repository's original code. `scripts/check_release_readiness.py` reports this as a release warning
rather than silently assuming a license.
