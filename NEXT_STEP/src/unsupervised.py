"""
unsupervised.py — Phát hiện review nghi vấn bằng phương pháp không giám sát.

Module này thực hiện 2 kỹ thuật chính:
1. Near-duplicate detection: tìm các review có nội dung gần giống nhau
   bằng TF-IDF cosine similarity hoặc MinHash/LSH.
2. Clustering: nhóm các review theo đặc điểm nội dung để phát hiện
   cụm review bất thường (spam cluster).

Dùng như một lớp bổ sung bên cạnh heuristic labeling trong PREPROCESSING.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

def build_tfidf_matrix(texts: list[str], max_features: int = 5000):
    """Xây dựng ma trận TF-IDF từ danh sách văn bản đã clean."""
    vectorizer = TfidfVectorizer(
        max_features=max_features,
        ngram_range=(1, 2),
        min_df=2,
        analyzer="char_wb",  # char n-gram tốt hơn cho tiếng Việt không dấu
    )
    matrix = vectorizer.fit_transform(texts)
    return vectorizer, matrix


def find_near_duplicates(
    df: pd.DataFrame,
    text_col: str = "content_clean",
    id_col: str = "review_id",
    threshold: float = 0.85,
) -> pd.DataFrame:
    """
    Tìm các cặp review có nội dung gần giống nhau (cosine similarity >= threshold).

    Returns:
        DataFrame với các cột: review_id_a, review_id_b, similarity_score
    """
    if df.empty or text_col not in df.columns:
        return pd.DataFrame(columns=["review_id_a", "review_id_b", "similarity_score"])

    texts = df[text_col].fillna("").tolist()
    ids = df[id_col].tolist()

    _, matrix = build_tfidf_matrix(texts)

    # Tính similarity từng cặp (batch để tránh OOM với dataset lớn)
    results: list[dict[str, Any]] = []
    batch_size = 500
    n = len(texts)

    for i in range(0, n, batch_size):
        batch = matrix[i : i + batch_size]
        sims = cosine_similarity(batch, matrix)  # shape: (batch_size, n)
        for local_idx, row in enumerate(sims):
            global_idx = i + local_idx
            # Chỉ lấy nửa trên của ma trận (tránh duplicate pair)
            for j in range(global_idx + 1, n):
                score = float(row[j])
                if score >= threshold:
                    results.append({
                        "review_id_a": ids[global_idx],
                        "review_id_b": ids[j],
                        "similarity_score": round(score, 4),
                    })

    return pd.DataFrame(results)


def flag_near_duplicates(
    df: pd.DataFrame,
    threshold: float = 0.85,
    text_col: str = "content_clean",
    id_col: str = "review_id",
) -> pd.DataFrame:
    """
    Thêm cột `r_near_duplicate` (bool) vào DataFrame.
    Review bị đánh dấu nếu nó là một phần của cặp near-duplicate.
    """
    pairs = find_near_duplicates(df, text_col=text_col, id_col=id_col, threshold=threshold)
    flagged_ids: set[str] = set()
    if not pairs.empty:
        flagged_ids = set(pairs["review_id_a"]) | set(pairs["review_id_b"])

    result = df.copy()
    result["r_near_duplicate"] = result[id_col].isin(flagged_ids)
    result["near_dup_count"] = result[id_col].map(
        lambda rid: (
            (pairs["review_id_a"] == rid).sum() + (pairs["review_id_b"] == rid).sum()
            if not pairs.empty else 0
        )
    )
    return result


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_reviews(
    df: pd.DataFrame,
    text_col: str = "content_clean",
    n_clusters: int = 10,
) -> pd.DataFrame:
    """
    Phân cụm (cluster) các review bằng K-Means trên không gian TF-IDF.
    Thêm cột `cluster_id` vào DataFrame.

    Gợi ý: cluster có median word_count thấp + high fake_rate = spam cluster.
    """
    try:
        from sklearn.cluster import MiniBatchKMeans
    except ImportError:
        raise ImportError("scikit-learn is required for clustering")

    texts = df[text_col].fillna("").tolist()
    _, matrix = build_tfidf_matrix(texts)

    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
    labels = kmeans.fit_predict(matrix)

    result = df.copy()
    result["cluster_id"] = labels
    return result


def summarize_clusters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tóm tắt thống kê theo cluster để phát hiện cluster nghi vấn.

    Returns:
        DataFrame với thống kê: cluster_id, size, median_word_count, fake_rate, sample_review
    """
    if "cluster_id" not in df.columns:
        raise ValueError("Run cluster_reviews() first to add cluster_id column")

    stats = (
        df.groupby("cluster_id")
        .agg(
            size=("cluster_id", "count"),
            median_word_count=("word_count", "median") if "word_count" in df.columns else ("cluster_id", "count"),
            fake_rate=("is_fake", "mean") if "is_fake" in df.columns else ("cluster_id", "count"),
        )
        .reset_index()
    )
    return stats.sort_values("fake_rate", ascending=False)
