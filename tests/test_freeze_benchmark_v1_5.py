from hashlib import sha256
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from freeze_benchmark_v1_5 import (  # noqa: E402
    HASHED_FILES,
    LOCKED_TEST_EVENTS,
    LOCKED_THRESHOLD,
    build_manifest,
    read_reviewer_contract,
    sha256_file,
    validate_locked_protocol,
)


def test_sha256_file_hashes_exact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_bytes(b"benchmark-v1.5")
    assert sha256_file(artifact) == sha256(b"benchmark-v1.5").hexdigest()


def test_locked_protocol_matches_public_runtime() -> None:
    contract = validate_locked_protocol(PROJECT_ROOT)
    assert contract["selected_review_threshold"] == LOCKED_THRESHOLD
    assert contract["prompt_version"] == "event_stance_v2"
    assert contract["short_text_max_chars"] == 4


def test_manifest_records_source_commit_and_no_secrets() -> None:
    manifest = build_manifest(
        PROJECT_ROOT,
        git={
            "commit": "a" * 40,
            "branch": "benchmark/v1.5-freeze",
            "worktree_clean_before_freeze": True,
        },
        frozen_at_utc="2026-07-29T00:00:00+00:00",
    )
    assert manifest["git"]["source_commit"] == "a" * 40
    assert manifest["evaluation_contract"]["test_events"] == LOCKED_TEST_EVENTS
    assert set(manifest["artifact_sha256"]) == set(HASHED_FILES)
    assert not any(manifest["privacy"].values())


def test_reviewer_contract_fails_closed_when_constant_missing(
    tmp_path: Path,
) -> None:
    reviewer = tmp_path / "src/opinion_agent/agent"
    reviewer.mkdir(parents=True)
    (reviewer / "reviewer.py").write_text(
        'REVIEW_PROMPT_VERSION = "event_stance_v2"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="REVIEW_SHORT_TEXT_MAX_CHARS"):
        read_reviewer_contract(tmp_path)
