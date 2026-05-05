from __future__ import annotations

import pandas as pd

from src.feature_engineering import FEATURE_COLUMNS, build_features
from src.labeling import label_review
from src.nlp_utils import clean_text


def test_clean_text_keeps_vietnamese_accents():
    assert clean_text("  Sản phẩm TỐT!!!  ") == "sản phẩm tốt!!!"


def test_label_review_flags_suspicious_short_unverified_review():
    label = label_review({"review_id": "1", "rating": 5, "content": "Sản phẩm tốt", "purchased": False, "total_reviews": 1})
    assert label["is_fake"] == 1
    assert "r_extreme_rating" in label["flags"]
    assert "r_not_verified_purchase" in label["flags"]


def test_build_features_schema_is_stable():
    df = pd.DataFrame(
        [
            {
                "rating": 5,
                "content": "Sản phẩm tốt, giao nhanh",
                "helpful_count": 0,
                "purchased": False,
                "total_reviews": 1,
            }
        ]
    )
    features = build_features(df)
    assert list(features.columns) == FEATURE_COLUMNS
    assert features.shape == (1, len(FEATURE_COLUMNS))
