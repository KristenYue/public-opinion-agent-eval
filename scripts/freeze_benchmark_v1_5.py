"""Freeze the Benchmark v1.5 inference and evaluation protocol.

The command intentionally fails when the Git worktree is dirty. This prevents
test-event labels from being inspected before the exact code, prompt, routing
threshold, and event roster have been recorded.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("data/evaluation/benchmark_v1_5_freeze_manifest.json")
LOCKED_THRESHOLD = 0.80
LOCKED_REVIEWER_MODEL = "qwen-plus"
LOCKED_BOOTSTRAP_SEED = 20260729
LOCKED_TEST_EVENTS = [
    "中国队夺得2026机器人世界杯冠军",
    "学校强制老师无偿陪餐摊派到人",
    "国标版美素佳儿铅含量争议回应",
    "博物馆存包押金退还未到账",
]
HASHED_FILES = [
    "app.py",
    "src/opinion_agent/agent/reviewer.py",
    "src/opinion_agent/agent/nodes.py",
    "scripts/evaluate_event_aware_cascade.py",
    "data/evaluation/benchmark_v1_5_pilot_annotation_summary.json",
    "data/evaluation/benchmark_v1_5_pilot_queue.manifest.json",
    "docs/BENCHMARK_V1_5_PLAN.md",
    "docs/BENCHMARK_V1_5_EVENT_ROSTER.md",
]


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def run_git(project_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def git_state(project_root: Path) -> dict[str, Any]:
    status = run_git(project_root, "status", "--porcelain=v1", "--untracked-files=all")
    return {
        "commit": run_git(project_root, "rev-parse", "HEAD"),
        "branch": run_git(project_root, "branch", "--show-current"),
        "worktree_clean_before_freeze": not bool(status),
        "dirty_paths": status.splitlines(),
    }


def _extract_constant(source: str, name: str, pattern: str) -> str:
    match = re.search(rf"^{name}\s*=\s*{pattern}\s*$", source, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Cannot locate {name} in reviewer.py")
    return match.group(1)


def read_reviewer_contract(project_root: Path) -> dict[str, Any]:
    source = (
        project_root / "src/opinion_agent/agent/reviewer.py"
    ).read_text(encoding="utf-8")
    return {
        "prompt_version": _extract_constant(
            source, "REVIEW_PROMPT_VERSION", r'"([^"]+)"'
        ),
        "short_text_max_chars": int(
            _extract_constant(source, "REVIEW_SHORT_TEXT_MAX_CHARS", r"(\d+)")
        ),
        "library_default_review_threshold": float(
            _extract_constant(
                source, "REVIEW_CONFIDENCE_THRESHOLD", r"([0-9.]+)"
            )
        ),
    }


def validate_locked_protocol(project_root: Path) -> dict[str, Any]:
    final_metrics = json.loads(
        (
            project_root / "data/evaluation/event_aware_protocol_final_metrics.json"
        ).read_text(encoding="utf-8")
    )
    selected_threshold = float(final_metrics["selected_threshold"])
    if selected_threshold != LOCKED_THRESHOLD:
        raise ValueError(
            f"Expected selected threshold {LOCKED_THRESHOLD:.2f}, "
            f"found {selected_threshold:.2f}"
        )

    app_source = (project_root / "app.py").read_text(encoding="utf-8")
    expected_setting = (
        f'os.environ.setdefault("REVIEW_CONFIDENCE_THRESHOLD", '
        f'"{LOCKED_THRESHOLD:.2f}")'
    )
    if expected_setting not in app_source:
        raise ValueError("app.py does not lock the public review threshold to 0.80")

    missing = [path for path in HASHED_FILES if not (project_root / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen protocol files: {missing}")

    contract = read_reviewer_contract(project_root)
    contract["selected_review_threshold"] = selected_threshold
    return contract


def build_manifest(
    project_root: Path,
    *,
    git: dict[str, Any],
    frozen_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = validate_locked_protocol(project_root)
    hashes = {
        relative_path: sha256_file(project_root / relative_path)
        for relative_path in HASHED_FILES
    }
    return {
        "schema_version": "1.0",
        "benchmark_version": "v1.5",
        "status": "frozen_before_test_annotation",
        "frozen_at_utc": frozen_at_utc
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git": {
            "source_commit": git["commit"],
            "source_branch": git["branch"],
            "worktree_clean_before_freeze": git["worktree_clean_before_freeze"],
        },
        "inference_contract": {
            "primary_model": "XGBoost",
            "reviewer_model": LOCKED_REVIEWER_MODEL,
            **contract,
            "human_fallback_is_not_model_accuracy": True,
        },
        "evaluation_contract": {
            "split_unit": "event_id",
            "validation_only_threshold_selection": True,
            "test_labels_single_final_evaluation": True,
            "bootstrap_seed": LOCKED_BOOTSTRAP_SEED,
            "test_events": LOCKED_TEST_EVENTS,
        },
        "artifact_sha256": hashes,
        "privacy": {
            "contains_api_key": False,
            "contains_cookie": False,
            "contains_raw_private_comments": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Manifest path relative to the project root.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = git_state(PROJECT_ROOT)
    if not state["worktree_clean_before_freeze"]:
        details = "\n".join(state["dirty_paths"])
        raise SystemExit(
            "Refusing to freeze Benchmark v1.5: Git worktree is not clean.\n"
            "Commit the intended protocol changes first, then rerun.\n"
            f"{details}"
        )

    manifest = build_manifest(PROJECT_ROOT, git=state)
    output = args.output
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Benchmark v1.5 frozen at source commit {state['commit']}")
    print(f"Manifest: {output}")


if __name__ == "__main__":
    main()
