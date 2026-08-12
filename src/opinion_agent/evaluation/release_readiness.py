"""Release-readiness checks for the public portfolio repository."""

from pathlib import Path
from typing import Any
import hashlib
import json
import re
import shutil
import subprocess

from .prompt_regression import evaluate_prompt_regression


REQUIRED_FILES = (
    "README.md",
    "ANNOTATION_GUIDE.md",
    "DATA_CARD.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM.md",
    "Dockerfile",
    "examples/demo_event_cards.jsonl",
    "artifacts/legacy_baseline/manifest.json",
    "data/evaluation/transformer_sentiment_metrics_summary.json",
    "data/evaluation/prompt_regression_baseline.json",
    "data/evaluation/reviewer_confidence_diagnostics.json",
    "data/evaluation/deployment_verification_2026-08-12.json",
    "artifacts/legacy_baseline/xgboost_sentiment_model.joblib",
    "artifacts/legacy_baseline/tfidf_vectorizer.joblib",
    "artifacts/legacy_baseline/label_encoder.joblib",
)
PRIVATE_IGNORE_RULES = (
    ".idea/",
    "data/raw_private/",
    "data/processed/comments_deduplicated.csv",
    "data/processed/event_cards.jsonl",
    "data/evaluation/*.jsonl",
    "data/modeling/transformer_sentiment/*.jsonl",
    "dictionaries/",
    "tmp/",
    "artifacts/transformer_sentiment_*/",
    "*.safetensors",
    "optimizer.pt",
    ".env",
)
DOCKER_IGNORE_RULES = (
    ".idea",
    "data/raw_private",
    "data/legacy_split",
    "data/annotations",
    "data/modeling/transformer_sentiment/*.jsonl",
    "dictionaries",
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
LEGACY_ARTIFACT_FILES = {
    "artifacts/legacy_baseline/xgboost_sentiment_model.joblib",
    "artifacts/legacy_baseline/tfidf_vectorizer.joblib",
    "artifacts/legacy_baseline/label_encoder.joblib",
}
PROHIBITED_PUBLIC_PATHS = (
    "dictionaries/BosonNLP_sentiment_score.txt",
    "dictionaries/hownet/pos_emotion.txt",
    "dictionaries/hownet/neg_emotion.txt",
    "dictionaries/stopwords.txt",
    "dictionaries/否定词_融合版.txt",
)
PROHIBITED_PUBLIC_PREFIXES = (
    ".idea/",
    "data/raw_private/",
    "data/legacy_split/",
    "data/annotations/",
    "docs/_local/",
    "legacy/",
    "references/",
    "dictionaries/",
    "outputs/",
    "tmp/",
    "artifacts/transformer_sentiment_",
)
PROHIBITED_PUBLIC_NAMES = {
    ".env",
    "optimizer.pt",
    "rng_state.pth",
    "scheduler.pt",
}
MAX_PUBLIC_FILE_BYTES = 20 * 1024 * 1024


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

    public_tree = audit_public_tree(root)
    record(
        "public_tree_scope",
        public_tree["passed"],
        f"files={public_tree['file_count']}; failures={public_tree['failures']}",
    )

    prohibited = [path for path in PROHIBITED_PUBLIC_PATHS if (root / path).is_file()]
    record(
        "unlicensed_dictionary_assets_absent",
        not prohibited,
        f"present={prohibited}",
    )

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

    artifact_integrity = evaluate_artifact_integrity(root)
    record(
        "legacy_artifact_integrity",
        artifact_integrity["passed"],
        f"verified={artifact_integrity['verified']}; "
        f"failures={artifact_integrity['failures']}",
    )

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

    deployment = _read_json(
        root / "data" / "evaluation" / "deployment_verification_2026-08-12.json"
    )
    public_page = deployment.get("public_page", {})
    preset = deployment.get("preset_demo", {})
    strict = deployment.get("strict_input", {})
    privacy = deployment.get("privacy_scan", {})
    deployment_ok = (
        deployment.get("status") == "passed_with_limitations"
        and public_page.get("running") is True
        and preset.get("fast_path") == 2
        and preset.get("qwen_reviewed") == 2
        and preset.get("manual_required") == 1
        and strict.get("policy_version") == "strict_live_test_v1"
        and strict.get("errors") == []
        and privacy.get("sensitive_findings") == []
    )
    record(
        "public_deployment_evidence",
        deployment_ok,
        f"status={deployment.get('status')}; health={deployment.get('health_endpoint')}",
    )

    prompt_gate = evaluate_prompt_regression(root)
    record(
        "prompt_regression_gate",
        prompt_gate["passed"],
        f"version={prompt_gate.get('prompt_version')}; failures={prompt_gate.get('failures')}",
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


def evaluate_artifact_integrity(project_root: str | Path) -> dict[str, Any]:
    """Verify repository-owned serialized assets before they can be released."""
    root = Path(project_root).resolve()
    manifest_path = root / "artifacts" / "legacy_baseline" / "manifest.json"
    if not manifest_path.is_file():
        return {"passed": False, "verified": 0, "failures": ["manifest_missing"]}

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "passed": False,
            "verified": 0,
            "failures": [f"manifest_unreadable:{type(exc).__name__}"],
        }

    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        return {"passed": False, "verified": 0, "failures": ["manifest_files_invalid"]}

    failures: list[str] = []
    verified = 0
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failures.append(f"entry_{index}:invalid")
            continue
        relative_path = str(entry.get("path", ""))
        expected_hash = str(entry.get("sha256", "")).lower()
        expected_size = entry.get("bytes")
        if relative_path in seen_paths:
            failures.append(f"{relative_path}:duplicate")
            continue
        seen_paths.add(relative_path)
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            failures.append(f"{relative_path}:outside_project")
            continue
        if not candidate.is_file():
            failures.append(f"{relative_path}:missing")
            continue
        if not isinstance(expected_size, int) or expected_size < 0:
            failures.append(f"{relative_path}:invalid_size")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            failures.append(f"{relative_path}:invalid_sha256")
            continue
        actual_size = candidate.stat().st_size
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_size != expected_size:
            failures.append(f"{relative_path}:size_mismatch")
            continue
        if actual_hash != expected_hash:
            failures.append(f"{relative_path}:sha256_mismatch")
            continue
        verified += 1

    missing_entries = sorted(LEGACY_ARTIFACT_FILES - seen_paths)
    unexpected_entries = sorted(seen_paths - LEGACY_ARTIFACT_FILES)
    failures.extend(f"{path}:manifest_entry_missing" for path in missing_entries)
    failures.extend(f"{path}:manifest_entry_unexpected" for path in unexpected_entries)

    return {"passed": not failures, "verified": verified, "failures": failures}


def audit_public_tree(project_root: str | Path) -> dict[str, Any]:
    """Audit tracked and non-ignored untracked files as the next public commit set."""
    root = Path(project_root).resolve()
    if shutil.which("git") is None:
        return {"passed": False, "file_count": 0, "failures": ["git_unavailable"]}

    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "passed": False,
            "file_count": 0,
            "failures": [f"git_ls_files_failed:{result.returncode}"],
        }

    paths = [
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    ]
    existing = [path for path in paths if (root / path).is_file()]
    failures: list[str] = []
    for path in existing:
        file_path = root / path
        if path in PROHIBITED_PUBLIC_NAMES or any(
            path.startswith(prefix) for prefix in PROHIBITED_PUBLIC_PREFIXES
        ):
            failures.append(f"{path}:prohibited_path")
        if path.endswith(".safetensors"):
            failures.append(f"{path}:prohibited_model_weight")
        if file_path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
            failures.append(f"{path}:oversized")

    return {
        "passed": not failures,
        "file_count": len(existing),
        "failures": sorted(set(failures)),
    }


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
