from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from PREPROCESSING.nlp_utils import (
    caps_ratio,
    clean_text,
    count_words,
    is_noise_text,
    is_only_generic,
)


# ---------------------------------------------------------------------------
# Default signal weights — tier-based
# ---------------------------------------------------------------------------
SIGNAL_WEIGHTS: dict[str, float] = {
    # Strong — high-confidence spam / bot patterns
    "s_noise": 1.5,
    "s_duplicate_content": 1.5,
    "s_burst_review": 1.2,
    # Medium — suspicious but may occur in genuine reviews
    "m_only_generic": 0.8,
    "m_angry_short": 0.7,
    "m_empty_praise": 0.7,
    "m_excessive_caps": 0.6,
    # Weak — common on Tiki, only supplementary evidence
    "w_zero_activity": 0.4,
    "w_rating_deviation": 0.3,
    "w_short_content": 0.2,
}


@dataclass(frozen=True)
class LabelingConfig:
    score_threshold: float = 1.8
    weights: dict[str, float] = field(default_factory=lambda: dict(SIGNAL_WEIGHTS))
    label_version: str = "heuristic_v3"


def label_review(
    review: dict[str, Any],
    config: LabelingConfig | None = None,
    *,
    duplicate_contents: set[str] | None = None,
    user_daily_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Score a single review using weighted heuristic signals."""
    cfg = config or LabelingConfig()
    w = cfg.weights

    content_raw = review.get("content") or review.get("content_clean") or ""
    content_clean = clean_text(content_raw)
    word_count = count_words(content_clean)
    rating = review.get("rating")
    helpful = int(review.get("helpful_count") or 0)
    total_reviews = int(
        review.get("total_reviews") or review.get("user_total_reviews") or 0
    )
    avg_rating = float(review.get("avg_rating_given") or rating or 0)

    signals: list[str] = []
    score = 0.0

    # ── Strong signals ──────────────────────────────────────────────────
    if is_noise_text(content_clean):
        signals.append("s_noise")
        score += w.get("s_noise", 0)

    if duplicate_contents is not None:
        key = content_clean[:80]
        if key in duplicate_contents:
            signals.append("s_duplicate_content")
            score += w.get("s_duplicate_content", 0)

    user_id = str(review.get("user_id") or "")
    if user_daily_counts and user_daily_counts.get(user_id, 0) >= 3:
        signals.append("s_burst_review")
        score += w.get("s_burst_review", 0)

    # ── Medium signals ──────────────────────────────────────────────────
    if is_only_generic(content_clean):
        signals.append("m_only_generic")
        score += w.get("m_only_generic", 0)

    if rating == 1 and word_count < 5:
        signals.append("m_angry_short")
        score += w.get("m_angry_short", 0)

    if rating == 5 and word_count < 4 and helpful == 0:
        signals.append("m_empty_praise")
        score += w.get("m_empty_praise", 0)

    if caps_ratio(content_raw) > 0.5 and len(content_clean) > 10:
        signals.append("m_excessive_caps")
        score += w.get("m_excessive_caps", 0)

    # ── Weak signals ────────────────────────────────────────────────────
    if total_reviews == 0:
        signals.append("w_zero_activity")
        score += w.get("w_zero_activity", 0)

    if rating and avg_rating and abs(rating - avg_rating) >= 3:
        signals.append("w_rating_deviation")
        score += w.get("w_rating_deviation", 0)

    if word_count < 3 and not is_noise_text(content_clean):
        signals.append("w_short_content")
        score += w.get("w_short_content", 0)

    # ── Final label ─────────────────────────────────────────────────────
    is_fake = int(score >= cfg.score_threshold)
    fake_prob = min(0.95, round(score / 4.0, 3))

    return {
        "review_id": str(review.get("review_id")),
        "product_id": str(review.get("product_id") or ""),
        "user_id": user_id,
        "rating": rating,
        "content_clean": content_clean,
        "is_fake": is_fake,
        "fake_probability": fake_prob,
        "flag_count": len(signals),
        "flags": signals,
        "suspicion_score": round(score, 2),
        "label_version": cfg.label_version,
    }


def label_dataframe(
    df: pd.DataFrame, config: LabelingConfig | None = None
) -> pd.DataFrame:
    """Label an entire DataFrame, computing batch-level signals first."""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "review_id",
                "product_id",
                "user_id",
                "rating",
                "content_clean",
                "is_fake",
                "fake_probability",
                "flag_count",
                "flags",
                "suspicion_score",
                "label_version",
            ]
        )

    # --- Pre-compute batch-level signals ---

    # Duplicate content detection: keep first 80 chars as key
    contents = df.apply(
        lambda r: clean_text(r.get("content") or r.get("content_clean"))[:80],
        axis=1,
    )
    dup_counts = contents.value_counts()
    duplicate_contents = set(dup_counts[dup_counts > 1].index)

    # Burst review detection: users reviewing ≥ 3 products on the same day
    user_daily: dict[str, int] = {}
    if "created_at" in df.columns:
        df_temp = df.copy()
        df_temp["_date"] = pd.to_datetime(
            df_temp["created_at"], errors="coerce"
        ).dt.date
        for (uid, _d), group in df_temp.groupby(["user_id", "_date"]):
            if len(group) >= 3:
                user_daily[str(uid)] = len(group)

    records = [
        label_review(
            row,
            config,
            duplicate_contents=duplicate_contents,
            user_daily_counts=user_daily,
        )
        for row in df.to_dict("records")
    ]
    return pd.DataFrame(records)


def fake_rate(labels: pd.DataFrame) -> float:
    if labels.empty:
        return 0.0
    return float(labels["is_fake"].mean())
