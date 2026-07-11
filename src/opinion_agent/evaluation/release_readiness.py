"""Release-readiness checks for the public portfolio repository."""

from pathlib import Path
from typing import Any
import json
import re
import shutil


REQUIRED_FILES = (
    "README.md",
    "DATA_CARD.md",
    "SECURITY.md",
    "UPSTREAM.md",
    "Dockerfile",
    "examples/demo_event_cards.jsonl",
    "data/evaluation/transformer_sentiment_metrics_summary.json",
    "artifacts/legacy_baseline/xgboost_sentiment_model.joblib",
    "artifacts/legacy_baseline/tfidf_vectorizer.joblib",
    "artifacts/legacy_baseline/label_encoder.joblib",
)
PRIVATE_IGNORE_RULES = (
    "data/raw_private/",
    "data/processed/comments_deduplicated.csv",
    "data/processed/event_cards.jsonl",
    "data/evaluation/*.jsonl",
    "data/modeling/transformer_sentiment/*.jsonl",
    "tmp/",
    "artifacts/transformer_sentiment_*/",
    "*.safetensors",
    "optimizer.pt",
    ".env",
)
DOCKER_IGNORE_RULES = (
    "data/raw_private",
    "data/legacy_split",
    "data/annotations",
    "data/modeling/transformer_sentiment/*.jsonl",
    "artifacts/transformer_sentiment_*",
    "*.safetensors",
    "tmp",
)
SCAN_DIRECTORIES = ("src", "scripts", "tests", "docs", "examples")
SCAN_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".jsonl",
    ".js",
    ".css",
    ".html",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
    re.compile(r"SUB=[A-Za-z0-9%_-]{20,}"),
)


def evaluate_release_readiness(project_root: str | Path) -> dict[str, Any]:
    """Return deterministic repository checks plus environment-specific warnings."""
    root = Path(project_root)
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str, severity: str = "error") -> None:
        checks.append(
            {"name": name, "passed": bool(passed), "severity": severity, "detail": detail}
        )

    missing = [path for path in REQUIRED_FILES if not (root / path).is_file()]
    record("required_public_files", not missing, f"missing={missing}")

    ignore_text = (root / ".gitignore").read_text(encoding="utf-8")
    missing_ignores = [rule for rule in PRIVATE_IGNORE_RULES if rule not in ignore_text]
    record("private_data_ignore_rules", not missing_ignores, f"missing={missing_ignores}")

    docker_ignore_text = (root / ".dockerignore").read_text(encoding="utf-8")
    missing_docker_ignores = [
        rule for rule in DOCKER_IGNORE_RULES if rule not in docker_ignore_text
    ]
    record(
        "docker_context_ignore_rules",
        not missing_docker_ignores,
        f"missing={missing_docker_ignores}",
    )

    demo_path = root / "examples" / "demo_event_cards.jsonl"
    demo_cards = [
        json.loads(line)
        for line in demo_path.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    demo_safe = len(demo_cards) >= 3 and all(
        card.get("source_file") == "synthetic_demo_data"
        and all(
            str(post.get("source_url", "")).startswith("https://example.com/synthetic/")
            for post in card.get("representative_posts", [])
        )
        for card in demo_cards
    )
    record("synthetic_demo_boundary", demo_safe, f"cards={len(demo_cards)}")

    agent_metrics = _read_json(
        root / "data" / "evaluation" / "agent_mvp_metrics_partial_adjudication.json"
    )
    failure_metrics = _read_json(
        root / "data" / "evaluation" / "failure_recovery_metrics.json"
    )
    metrics_ok = (
        agent_metrics.get("agent_contract_success_rate") == 1.0
        and failure_metrics.get("scenario_success_rate") == 1.0
    )
    record(
        "machine_readable_agent_evidence",
        metrics_ok,
        "contract_rate="
        f"{agent_metrics.get('agent_contract_success_rate')}; "
        f"failure_recovery_rate={failure_metrics.get('scenario_success_rate')}",
    )

    credential_hits = _scan_credentials(root)
    record("credential_pattern_scan", not credential_hits, f"hits={credential_hits}")

    record(
        "repository_license",
        (root / "LICENSE").is_file(),
        "LICENSE is absent; choose a code license only after third-party asset terms are reviewed.",
        severity="warning",
    )
    record(
        "docker_runtime_available",
        shutil.which("docker") is not None,
        "Docker executable is required to verify the image build.",
        severity="warning",
    )
    record(
        "git_runtime_available",
        shutil.which("git") is not None,
        "Git executable is required to audit the exact tracked-file set.",
        severity="warning",
    )

    failed_errors = [
        check["name"]
        for check in checks
        if not check["passed"] and check["severity"] == "error"
    ]
    warnings = [
        check["name"]
        for check in checks
        if not check["passed"] and check["severity"] == "warning"
    ]
    return {
        "status": "ready_with_warnings" if not failed_errors else "blocked",
        "passed": not failed_errors,
        "failed_checks": failed_errors,
        "warnings": warnings,
        "checks": checks,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _scan_credentials(root: Path) -> list[str]:
    hits: list[str] = []
    paths = [
        path
        for directory in SCAN_DIRECTORIES
        for path in (root / directory).rglob("*")
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES
    ]
    paths.extend(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES
    )
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS):
            hits.append(str(path.relative_to(root)))
    return sorted(set(hits))
