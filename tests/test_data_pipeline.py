from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.data_pipeline.audit import audit_comment_files, normalize_text  # noqa: E402


def test_normalize_text_removes_personal_mentions_and_urls() -> None:
    result = normalize_text("  @用户 请看 https://example.com 政策很好  ")
    assert "@用户" not in result
    assert "https://" not in result
    assert "[MENTION]" in result
    assert "[URL]" in result


def test_audit_deduplicates_globally(tmp_path: Path) -> None:
    pd.DataFrame({"content": ["相同评论", "独立评论"]}).to_csv(tmp_path / "A_comments.csv", index=False)
    pd.DataFrame({"content": ["相同评论"]}).to_csv(tmp_path / "B_comments.csv", index=False)
    data, audit = audit_comment_files(tmp_path)
    assert len(data) == 2
    assert audit.duplicate_rows_removed == 1
    assert set(data.columns) >= {"sample_id", "event_id", "normalized_text"}
