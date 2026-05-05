from __future__ import annotations

from PREPROCESSING.labeling import label_review
from PREPROCESSING.nlp_utils import clean_text


def test_clean_text_keeps_vietnamese_accents():
    assert clean_text("  Sản phẩm TỐT!!!  ") == "sản phẩm tốt!!!"


def test_label_v3_normal_review_is_not_fake():
    """A genuine short review with rating 5 should NOT be flagged as fake in v3."""
    label = label_review({
        "review_id": "1", "rating": 5, "content": "Sản phẩm tốt, pin rất trâu",
        "purchased": True, "total_reviews": 5, "avg_rating_given": 4.5,
    })
    assert label["is_fake"] == 0
    assert label["suspicion_score"] == 0.0


def test_label_v3_suspicious_duplicate_empty_praise():
    """A duplicate short praise from a zero-activity user should be flagged."""
    label = label_review(
        {
            "review_id": "2", "rating": 5, "content": "tốt",
            "helpful_count": 0, "total_reviews": 0, "avg_rating_given": 0,
        },
        duplicate_contents={"tốt"},
    )
    assert label["is_fake"] == 1
    assert label["suspicion_score"] >= 1.8
    assert "s_duplicate_content" in label["flags"]
    assert "w_zero_activity" in label["flags"]

