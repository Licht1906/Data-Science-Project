from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from src.nlp_utils import caps_ratio, clean_text, count_words, has_generic_phrase


FEATURE_COLUMNS = [
    "rating",
    "is_5star",
    "is_1star",
    "content_length",
    "word_count",
    "helpful_count",
    "purchased",
    "user_total_reviews",
    "user_avg_rating_given",
    "is_new_user",
    "review_hour",
    "day_of_week",
    "is_night",
    "exclamation_count",
    "caps_ratio",
    "repeat_char_count",
    "unique_word_ratio",
    "generic_phrase",
    "rating_product_delta",
    "product_avg_rating",
    "product_review_count",
]

FEATURE_LABELS_VI = {
    "rating": "Điểm đánh giá",
    "is_5star": "Review 5 sao",
    "is_1star": "Review 1 sao",
    "content_length": "Độ dài nội dung",
    "word_count": "Số từ",
    "helpful_count": "Lượt hữu ích",
    "purchased": "Đã xác nhận mua",
    "user_total_reviews": "Tổng review của tài khoản",
    "user_avg_rating_given": "Điểm trung bình tài khoản đã cho",
    "is_new_user": "Tài khoản ít hoạt động",
    "review_hour": "Giờ viết review",
    "day_of_week": "Thứ trong tuần",
    "is_night": "Viết ban đêm",
    "exclamation_count": "Số dấu chấm than",
    "caps_ratio": "Tỷ lệ chữ in hoa",
    "repeat_char_count": "Ký tự lặp bất thường",
    "unique_word_ratio": "Tỷ lệ từ không trùng lặp",
    "generic_phrase": "Có cụm từ chung chung",
    "rating_product_delta": "Chênh lệch rating so với sản phẩm",
    "product_avg_rating": "Điểm trung bình sản phẩm",
    "product_review_count": "Số review của sản phẩm",
}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if data.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    content = _series(data, "content_clean", data.get("content", "")).fillna("")
    created = pd.to_datetime(data.get("created_at"), errors="coerce") if "created_at" in data else pd.Series(pd.NaT, index=data.index)

    features = pd.DataFrame(index=data.index)
    rating = pd.to_numeric(_series(data, "rating", 0), errors="coerce").fillna(0)
    features["rating"] = rating
    features["is_5star"] = (rating == 5).astype(int)
    features["is_1star"] = (rating == 1).astype(int)
    features["content_length"] = content.map(lambda value: len(clean_text(value)))
    features["word_count"] = content.map(count_words)
    features["helpful_count"] = pd.to_numeric(_series(data, "helpful_count", 0), errors="coerce").fillna(0)
    features["purchased"] = _series(data, "purchased", False).fillna(False).astype(int)
    features["user_total_reviews"] = pd.to_numeric(_series(data, "total_reviews", data.get("user_total_reviews", 0)), errors="coerce").fillna(0)
    features["user_avg_rating_given"] = pd.to_numeric(
        _series(data, "avg_rating_given", data.get("user_avg_rating_given", rating.mean() or 0)),
        errors="coerce",
    ).fillna(rating.mean() or 0)
    features["is_new_user"] = (features["user_total_reviews"] < 3).astype(int)
    features["review_hour"] = created.dt.hour.fillna(12).astype(int)
    features["day_of_week"] = created.dt.dayofweek.fillna(0).astype(int)
    features["is_night"] = features["review_hour"].between(23, 23).astype(int) | features["review_hour"].between(0, 5).astype(int)
    features["exclamation_count"] = content.map(lambda value: str(value).count("!"))
    features["caps_ratio"] = content.map(caps_ratio)
    features["repeat_char_count"] = content.map(_repeat_char_count)
    features["product_avg_rating"] = pd.to_numeric(_series(data, "product_avg_rating", rating.mean() or 0), errors="coerce").fillna(rating.mean() or 0)
    features["product_review_count"] = pd.to_numeric(_series(data, "product_review_count", 0), errors="coerce").fillna(0)
    features["unique_word_ratio"] = content.map(_unique_word_ratio)
    features["generic_phrase"] = content.map(lambda value: int(has_generic_phrase(value)))
    features["rating_product_delta"] = (features["rating"] - features["product_avg_rating"]).abs()

    return features[FEATURE_COLUMNS].replace([np.inf, -np.inf], 0).fillna(0)


def build_prediction_frame(reviews: list[dict[str, Any]]) -> pd.DataFrame:
    return build_features(pd.DataFrame(reviews))


def _repeat_char_count(text: str | None) -> int:
    if not text:
        return 0
    return len(re.findall(r"(.)\1{2,}", str(text).lower()))


def _unique_word_ratio(text: str | None) -> float:
    words = clean_text(text).split()
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _series(data: pd.DataFrame, column: str, default: Any) -> pd.Series:
    if column in data:
        return data[column]
    if isinstance(default, pd.Series):
        return default.reindex(data.index)
    return pd.Series([default] * len(data), index=data.index)
