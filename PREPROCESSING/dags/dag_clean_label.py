from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from psycopg2.extras import execute_batch
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from airflow import DAG
from airflow.operators.python import PythonOperator

from PREPROCESSING.db import get_engine
from PREPROCESSING.ids import (
    SQL_DS_REVIEW_KEY_P,
    SQL_DS_REVIEW_KEY_PR,
    SQL_DS_REVIEW_KEY_R,
    canonical_text_id,
)
from PREPROCESSING.labeling import fake_rate, label_dataframe
from PREPROCESSING.nlp_utils import clean_text

default_args = {
    "owner": "N4-processing",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

_PROCESSING_SQL = """
INSERT INTO processed_reviews
    (review_id, product_id, user_id, rating, content_clean, is_fake, fake_probability, flag_count, flags, label_version, processed_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
ON CONFLICT (review_id) DO UPDATE SET
    content_clean = EXCLUDED.content_clean,
    is_fake = EXCLUDED.is_fake,
    fake_probability = EXCLUDED.fake_probability,
    flag_count = EXCLUDED.flag_count,
    flags = EXCLUDED.flags,
    label_version = EXCLUDED.label_version,
    processed_at = NOW()
"""


def _row_tuples(rows: list[dict]) -> list[tuple]:
    out: list[tuple] = []
    for row in rows:
        r_rating = row.get("rating")
        rating_val = int(r_rating) if r_rating is not None and pd.notna(r_rating) else None
        uid = row.get("user_id")
        uid_s = "" if uid is None or (isinstance(uid, float) and pd.isna(uid)) else str(uid)
        out.append(
            (
                canonical_text_id(row["review_id"]),
                str(row.get("product_id") or ""),
                uid_s,
                rating_val,
                str(row.get("content_clean") or ""),
                int(row["is_fake"]),
                float(row["fake_probability"]),
                int(row["flag_count"]),
                row["flags"],  # already JSON string
                str(row.get("label_version") or "heuristic_v2"),
            )
        )
    return out


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def clean_and_label():
    engine = get_engine()
    _ensure_processing_columns(engine)
    incremental = _env_bool("PREPROCESSING_INCREMENTAL", True)
    incremental_sql = ""
    if incremental:
        incremental_sql = (
            f"AND NOT EXISTS (SELECT 1 FROM processed_reviews pr "
            f"WHERE ({SQL_DS_REVIEW_KEY_PR}) = ({SQL_DS_REVIEW_KEY_R}))"
        )
    df = pd.read_sql(
        text(
            f"""
        SELECT r.*, u.total_reviews, u.avg_rating_given,
               p.rating_avg AS product_avg_rating, p.review_count AS product_review_count
        FROM raw_reviews r
        LEFT JOIN raw_users u ON r.user_id = u.user_id
        LEFT JOIN raw_products p ON r.product_id = p.product_id
        WHERE r.content IS NOT NULL AND trim(r.content) <> ''
        {incremental_sql}
        """
        ),
        engine,
    )
    df = _preprocess_reviews(df)
    labels = label_dataframe(df)
    fake_prob_series = labels["flag_count"].map(lambda count: min(0.95, 0.15 + int(count) * 0.2))
    labels["fake_probability"] = fake_prob_series
    labels["label_version"] = "heuristic_v2"

    batch_rows = labels.to_dict("records")
    for row in batch_rows:
        row["flags"] = json.dumps(row["flags"], ensure_ascii=False)

    tuples = _row_tuples(batch_rows)

    chunk_max = max(50, min(2000, _env_int("PREPROCESSING_BATCH_SIZE", 800)))
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            for i in range(0, len(tuples), chunk_max):
                chunk = tuples[i : i + chunk_max]
                execute_batch(cursor, _PROCESSING_SQL, chunk, page_size=min(chunk_max, 500))
        raw_conn.commit()
    finally:
        raw_conn.close()

    pending_raw = pd.read_sql(
        text(
            f"""
            SELECT COUNT(*) AS n FROM raw_reviews r
            LEFT JOIN processed_reviews p ON ({SQL_DS_REVIEW_KEY_R}) = ({SQL_DS_REVIEW_KEY_P})
            WHERE r.content IS NOT NULL AND trim(r.content) <> '' AND p.review_id IS NULL
            """
        ),
        engine,
    ).iloc[0]["n"]

    summary = {
        "processed_this_run": len(labels),
        "fake_rate": fake_rate(labels),
        "incremental": incremental,
        "pending_raw_nonempty": int(pending_raw or 0),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crawl_metadata (crawl_key, last_value, updated_at)
                VALUES ('last_clean_label_summary', CAST(:summary AS TEXT), NOW())
                ON CONFLICT (crawl_key) DO UPDATE SET last_value = EXCLUDED.last_value, updated_at = NOW()
                """
            ),
            {"summary": json.dumps(summary, ensure_ascii=False)},
        )

    print(json.dumps(summary, ensure_ascii=False))
    return summary


def _preprocess_reviews(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    data = df.copy()
    data["review_id"] = data["review_id"].map(canonical_text_id)
    data = data[data["review_id"].str.len() > 0]
    data["content_clean"] = data["content"].map(clean_text)
    data = data[data["content_clean"].str.len() > 0]
    data["rating"] = pd.to_numeric(data["rating"], errors="coerce").clip(lower=1, upper=5)
    data["helpful_count"] = pd.to_numeric(data["helpful_count"], errors="coerce").fillna(0).clip(lower=0)
    data["total_reviews"] = pd.to_numeric(data["total_reviews"], errors="coerce").fillna(0).clip(lower=0)
    data["avg_rating_given"] = pd.to_numeric(data["avg_rating_given"], errors="coerce").fillna(
        data["rating"].mean() or 0
    )
    data = data.sort_values(["review_id", "crawled_at"], ascending=[True, False])
    return data.drop_duplicates(subset=["review_id"], keep="first")


def _ensure_processing_columns(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE processed_reviews
                    ADD COLUMN IF NOT EXISTS label_version TEXT DEFAULT 'heuristic_v1'
                """
            )
        )


def label_quality_report():
    engine = get_engine()
    row = pd.read_sql(
        text(
            """SELECT COUNT(*) AS n,
                        AVG(is_fake)::float AS fake_rate,
                        AVG(flag_count)::float AS avg_flags
                   FROM processed_reviews"""
        ),
        engine,
    ).iloc[0].to_dict()
    summary = {
        "processed_reviews": int(row["n"] or 0),
        "fake_rate": float(row["fake_rate"] or 0),
        "avg_flags": float(row["avg_flags"] or 0),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


_sch_raw = os.getenv("PREPROCESSING_SCHEDULE", "").strip()

with DAG(
    dag_id="dag_clean_label",
    default_args=default_args,
    description="DAG 2: clean text, dedupe, heuristic weak labels (Neon-ready: TIKI_DATA_DB + batched UPSERT).",
    schedule_interval=_sch_raw if _sch_raw else None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["tiki", "processing", "labeling"],
) as dag:
    clean_label_task = PythonOperator(
        task_id="clean_and_label",
        python_callable=clean_and_label,
        execution_timeout=timedelta(hours=_env_int("PREPROCESSING_TASK_TIMEOUT_HOURS", 4)),
    )
    report_task = PythonOperator(
        task_id="label_quality_report",
        python_callable=label_quality_report,
        execution_timeout=timedelta(minutes=30),
    )
    clean_label_task >> report_task
