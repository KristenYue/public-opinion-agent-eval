"""Prompt-version and frozen-evidence release gate."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


def evaluate_prompt_regression(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    baseline_path = root / "data" / "evaluation" / "prompt_regression_baseline.json"
    if not baseline_path.is_file():
        return {"passed": False, "failures": ["missing prompt regression baseline"]}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    reviewer_path = root / "src" / "opinion_agent" / "agent" / "reviewer.py"
    source = reviewer_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    version_match = re.search(r'^REVIEW_PROMPT_VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
    current_version = version_match.group(1) if version_match else None
    current_fingerprint = prompt_contract_fingerprint(source)

    evidence_path = root / str(baseline["evidence_file"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
    failures = []
    if current_version != baseline.get("prompt_version"):
        failures.append(
            f"prompt version changed: expected={baseline.get('prompt_version')} actual={current_version}"
        )
    if current_fingerprint != baseline.get("prompt_contract_sha256"):
        failures.append("prompt contract source changed without an accepted regression baseline")
    for path, expected in baseline.get("expected_metrics", {}).items():
        actual = nested_value(evidence, path)
        if not numbers_equal(actual, expected):
            failures.append(f"metric changed: {path} expected={expected} actual={actual}")
    return {
        "passed": not failures,
        "prompt_version": current_version,
        "prompt_contract_sha256": current_fingerprint,
        "evidence_file": baseline["evidence_file"],
        "failures": failures,
    }


def prompt_contract_fingerprint(source: str) -> str:
    """Hash the payload and request-body block that controls reviewer behavior."""
    start_marker = "        payload = {"
    end_marker = "        response, attempts = self._post_with_retry("
    try:
        start = source.index(start_marker)
        end = source.index(end_marker, start)
    except ValueError as exc:
        raise ValueError("reviewer prompt contract block was not found") from exc
    contract = source[start:end].replace("\r\n", "\n")
    return sha256(contract.encode("utf-8")).hexdigest()


def nested_value(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def numbers_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 1e-12
    return actual == expected
