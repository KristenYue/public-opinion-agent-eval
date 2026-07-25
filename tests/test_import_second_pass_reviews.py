from scripts.import_second_pass_reviews import validate_and_merge


def test_second_pass_import_is_fail_closed() -> None:
    reviews = [
        {
            "sample_id": "a",
            "human_label": "Neutral",
            "needs_review": True,
        }
    ]
    responses = [
        {
            "row_number": 7,
            "sample_id": "a",
            "first_label": "Neutral",
            "second_label": "146",
            "second_confidence": "146",
            "second_rationale": "146",
        }
    ]

    merged, report = validate_and_merge(reviews, responses)

    assert merged == reviews
    assert report["write_allowed"] is False
    assert report["valid_responses"] == 0


def test_second_pass_import_merges_only_complete_valid_set() -> None:
    reviews = [
        {
            "sample_id": "a",
            "human_label": "Neutral",
            "human_confidence": "Medium",
            "needs_review": True,
        },
        {
            "sample_id": "b",
            "human_label": "Positive",
            "needs_review": False,
        },
    ]
    responses = [
        {
            "row_number": 7,
            "sample_id": "a",
            "first_label": "Neutral",
            "second_label": "Negative",
            "second_confidence": "High",
            "second_rationale": "明确表达不满",
        }
    ]

    merged, report = validate_and_merge(reviews, responses)

    assert report["write_allowed"] is True
    assert report["changed_labels"] == 1
    assert report["remaining_needs_review"] == 0
    assert merged[0]["human_label"] == "Negative"
    assert merged[0]["first_pass_label"] == "Neutral"
    assert merged[0]["truth_status"] == "independent_second_pass_complete"
    assert merged[1] == reviews[1]
