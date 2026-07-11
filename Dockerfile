FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/app/.cache/huggingface \
    EVENT_CARDS_PATH=/app/examples/demo_event_cards.jsonl

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e . \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"

COPY artifacts/legacy_baseline ./artifacts/legacy_baseline
COPY examples/demo_event_cards.jsonl ./examples/demo_event_cards.jsonl

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "opinion_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
