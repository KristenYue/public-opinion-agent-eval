"""Run and persist the executable resume-target benchmark."""

import json
import tempfile
from pathlib import Path

from opinion_agent.evaluation.resume_target_benchmark import run_resume_target_benchmark


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "evaluation" / "resume_target_live_v1" / "report.json"
WORK_ROOT = ROOT / "tmp"
WORK_ROOT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="opinion-resume-target-", dir=WORK_ROOT) as directory:
    report = run_resume_target_benchmark(Path(directory))
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"sentiment": {key: report["sentiment"][key] for key in ("dataset", "baseline", "selective")}, "retrieval": {key: report["retrieval"][key] for key in ("total", "hits", "hit_rate")}, "passed": report["passed"]}, ensure_ascii=False, indent=2))
