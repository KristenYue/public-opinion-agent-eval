from opinion_agent.evaluation.resume_target_benchmark import run_resume_target_benchmark


def test_executable_resume_target_benchmark(tmp_path):
    report = run_resume_target_benchmark(tmp_path)
    assert report["passed"] is True
    assert report["sentiment"]["baseline"]["correct"] == 425
    assert report["sentiment"]["selective"] == {
        "auto": 467,
        "auto_correct": 353,
        "selective_accuracy": 353 / 467,
        "manual_review": 183,
    }
    assert report["retrieval"]["hits"] == 178
    assert report["retrieval"]["total"] == 200
