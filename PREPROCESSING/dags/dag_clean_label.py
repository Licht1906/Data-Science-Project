from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

from PREPROCESSING.labeling import fake_rate, label_dataframe
from PREPROCESSING.nlp_utils import clean_text


default_args = {
    "owner": "N4-processing",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def clean_and_label():
    hook = PostgresHook(postgres_conn_id="tiki_data")
    engine = hook.get_sqlalchemy_engine()
    _ensure_processing_columns(hook)
    df = pd.read_sql(
        """
        SELECT r.*, u.total_reviews, u.avg_rating_given,
               p.rating_avg AS product_avg_rating, p.review_count AS product_review_count
        FROM raw_reviews r
        LEFT JOIN raw_users u ON r.user_id = u.user_id
        LEFT JOIN raw_products p ON r.product_id = p.product_id
        WHERE r.content IS NOT NULL AND trim(r.content) <> ''
        """,
        engine,
    )
    df = _preprocess_reviews(df)
    labels = label_dataframe(df)

    with engine.begin() as connection:
        for row in labels.to_dict("records"):
            connection.exec_driver_sql(
                """
                INSERT INTO processed_reviews
                    (review_id, product_id, user_id, rating, content_clean, is_fake, fake_probability, flag_count, flags, label_version, processed_at)
                VALUES (%(review_id)s, %(product_id)s, %(user_id)s, %(rating)s, %(content_clean)s, %(is_fake)s, %(fake_probability)s, %(flag_count)s, %(flags)s::jsonb, %(label_version)s, NOW())
                ON CONFLICT (review_id) DO UPDATE SET
                    content_clean = EXCLUDED.content_clean,
                    is_fake = EXCLUDED.is_fake,
                    fake_probability = EXCLUDED.fake_probability,
                    flag_count = EXCLUDED.flag_count,
                    flags = EXCLUDED.flags,
                    label_version = EXCLUDED.label_version,
                    processed_at = NOW()
                """,
                {**row, "flags": json.dumps(row["flags"], ensure_ascii=False)},
            )
    summary = {"processed": len(labels), "fake_rate": fake_rate(labels)}
    hook.run(
        """
        INSERT INTO crawl_metadata (crawl_key, last_value, updated_at)
        VALUES ('last_clean_label_summary', %(summary)s, NOW())
        ON CONFLICT (crawl_key) DO UPDATE SET last_value = EXCLUDED.last_value, updated_at = NOW()
        """,
        parameters={"summary": json.dumps(summary, ensure_ascii=False)},
    )
    return summary


def _preprocess_reviews(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    data = df.copy()
    data["content_clean"] = data["content"].map(clean_text)
    data = data[data["content_clean"].str.len() > 0]
    data["rating"] = pd.to_numeric(data["rating"], errors="coerce").clip(lower=1, upper=5)
    data["helpful_count"] = pd.to_numeric(data["helpful_count"], errors="coerce").fillna(0).clip(lower=0)
    data["total_reviews"] = pd.to_numeric(data["total_reviews"], errors="coerce").fillna(0).clip(lower=0)
    data["avg_rating_given"] = pd.to_numeric(data["avg_rating_given"], errors="coerce").fillna(data["rating"].mean() or 0)
    data = data.sort_values(["review_id", "crawled_at"], ascending=[True, False])
    return data.drop_duplicates(subset=["review_id"], keep="first")


def _ensure_processing_columns(hook: PostgresHook) -> None:
    hook.run(
        """
        ALTER TABLE processed_reviews
            ADD COLUMN IF NOT EXISTS label_version TEXT DEFAULT 'heuristic_v1'
        """
    )


def label_quality_report():
    hook = PostgresHook(postgres_conn_id="tiki_data")
    result = hook.get_first("SELECT COUNT(*), AVG(is_fake), AVG(flag_count) FROM processed_reviews")
    summary = {"processed_reviews": result[0], "fake_rate": float(result[1] or 0), "avg_flags": float(result[2] or 0)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


with DAG(
    dag_id="dag_clean_label",
    default_args=default_args,
    description="DAG 2: clean text, deduplicate and apply heuristic weak labels.",
    schedule_interval=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["tiki", "processing", "labeling"],
) as dag:
    clean_label_task = PythonOperator(task_id="clean_and_label", python_callable=clean_and_label)
    report_task = PythonOperator(task_id="label_quality_report", python_callable=label_quality_report)
    clean_label_task >> report_task
