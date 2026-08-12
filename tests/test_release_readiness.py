from pathlib import Path
import hashlib
import json
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.release_readiness import (  # noqa: E402
    audit_public_tree,
    evaluate_artifact_integrity,
    evaluate_release_readiness,
)


def test_public_repository_passes_release_blocking_checks() -> None:
    report = evaluate_release_readiness(PROJECT_ROOT)
    checks = {check["name"]: check for check in report["checks"]}

    assert report["passed"] is True
    assert report["failed_checks"] == []
    assert checks["required_public_files"]["passed"] is True
    assert checks["public_tree_scope"]["passed"] is True
    assert checks["unlicensed_dictionary_assets_absent"]["passed"] is True
    assert checks["private_data_ignore_rules"]["passed"] is True
    assert checks["docker_context_ignore_rules"]["passed"] is True
    assert checks["synthetic_demo_boundary"]["passed"] is True
    assert checks["legacy_artifact_integrity"]["passed"] is True
    assert checks["machine_readable_agent_evidence"]["passed"] is True
    assert checks["public_deployment_evidence"]["passed"] is True
    assert checks["prompt_regression_gate"]["passed"] is True
    assert checks["credential_pattern_scan"]["passed"] is True


def test_artifact_integrity_rejects_modified_serialized_asset(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts" / "legacy_baseline"
    artifact_dir.mkdir(parents=True)
    asset = artifact_dir / "model.joblib"
    asset.write_bytes(b"modified")
    (artifact_dir / "manifest.json").write_text(
        """{
          "files": [{
            "path": "artifacts/legacy_baseline/model.joblib",
            "bytes": 8,
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
          }]
        }""",
        encoding="utf-8",
    )

    report = evaluate_artifact_integrity(tmp_path)

    assert report["passed"] is False
    assert report["verified"] == 0
    assert "artifacts/legacy_baseline/model.joblib:sha256_mismatch" in report["failures"]
    assert "artifacts/legacy_baseline/model.joblib:manifest_entry_unexpected" in report[
        "failures"
    ]
    assert sum(item.endswith(":manifest_entry_missing") for item in report["failures"]) == 3


def test_artifact_integrity_rejects_incomplete_manifest(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts" / "legacy_baseline"
    artifact_dir.mkdir(parents=True)
    asset = artifact_dir / "xgboost_sentiment_model.joblib"
    asset.write_bytes(b"model")
    asset_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "artifacts/legacy_baseline/xgboost_sentiment_model.joblib",
                        "bytes": 5,
                        "sha256": asset_hash,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_artifact_integrity(tmp_path)

    assert report["passed"] is False
    assert report["verified"] == 1
    assert sorted(report["failures"]) == [
        "artifacts/legacy_baseline/label_encoder.joblib:manifest_entry_missing",
        "artifacts/legacy_baseline/tfidf_vectorizer.joblib:manifest_entry_missing",
    ]


def test_public_tree_audit_rejects_ide_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    idea_dir = tmp_path / ".idea"
    idea_dir.mkdir()
    (idea_dir / "workspace.xml").write_text("<project />", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--intent-to-add", ".idea/workspace.xml"],
        cwd=tmp_path,
        check=True,
    )

    report = audit_public_tree(tmp_path)

    assert report["passed"] is False
    assert report["failures"] == [".idea/workspace.xml:prohibited_path"]
