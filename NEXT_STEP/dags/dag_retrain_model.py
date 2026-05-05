from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

from src.modeling import train_baseline_models


default_args = {
    "owner": "N5-ml",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}


def check_data_sufficiency():
    hook = PostgresHook(postgres_conn_id="tiki_data")
    total, fake_rate = hook.get_first("SELECT COUNT(*), AVG(is_fake) FROM processed_reviews")
    fake_rate = float(fake_rate or 0)
    if int(total or 0) < int(os.getenv("MIN_TRAIN_SAMPLES", "200")):
        return "skip_retrain"
    if fake_rate < 0.01 or fake_rate > 0.5:
        return "skip_retrain"
    return "train_and_evaluate"


def train_and_evaluate(**context):
    hook = PostgresHook(postgres_conn_id="tiki_data")
    engine = hook.get_sqlalchemy_engine()
    df = pd.read_sql(
        """
        SELECT p.*, r.content, r.created_at, r.helpful_count, r.purchased,
               u.total_reviews, u.avg_rating_given,
               rp.rating_avg AS product_avg_rating, rp.review_count AS product_review_count
        FROM processed_reviews p
        JOIN raw_reviews r ON p.review_id = r.review_id
        LEFT JOIN raw_users u ON p.user_id = u.user_id
        LEFT JOIN raw_products rp ON p.product_id = rp.product_id
        """,
        engine,
    )
    result = train_baseline_models(df, model_dir=os.getenv("MODEL_DIR", "models"))
    context["ti"].xcom_push(key="train_result", value=result.__dict__)
    return result.__dict__


def compare_and_decide(**context):
    result = context["ti"].xcom_pull(task_ids="train_and_evaluate", key="train_result")
    hook = PostgresHook(postgres_conn_id="tiki_data")
    active = hook.get_first("SELECT auc_pr FROM model_registry WHERE is_active = TRUE ORDER BY trained_at DESC LIMIT 1")
    active_auc_pr = float(active[0]) if active and active[0] is not None else -1.0
    return "deploy_new_model" if result["auc_pr"] >= active_auc_pr else "keep_current_model"


def _ensure_model_registry_schema(hook: PostgresHook) -> None:
    hook.run("ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS metrics_path TEXT")
    hook.run("ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS model_name TEXT")
    hook.run("ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS threshold REAL")
    hook.run("ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS metrics_detail JSONB")


def deploy_new_model(**context):
    result = context["ti"].xcom_pull(task_ids="train_and_evaluate", key="train_result")
    active_path = Path(os.getenv("MODEL_PATH", "models/xgb_model.pkl"))
    active_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(result["model_path"], active_path)

    metrics_path = Path(result["metrics_path"])
    metrics_detail = json.loads(metrics_path.read_text(encoding="utf-8"))

    hook = PostgresHook(postgres_conn_id="tiki_data")
    _ensure_model_registry_schema(hook)
    hook.run("UPDATE model_registry SET is_active = FALSE WHERE is_active = TRUE")
    hook.run(
        """
        INSERT INTO model_registry (
            model_path, model_name, auc_pr, f1_score, auc_roc, threshold,
            n_train, fake_rate, metrics_path, metrics_detail, is_active, notes
        )
        VALUES (
            %(model_path)s, %(model_name)s, %(auc_pr)s, %(f1_score)s, %(auc_roc)s, %(threshold)s,
            %(n_train)s, %(fake_rate)s, %(metrics_path)s, CAST(%(metrics_detail)s AS jsonb), TRUE, %(notes)s
        )
        """,
        parameters={
            **result,
            "model_path": str(active_path),
            "notes": f"Auto deployed {result['model_name']}",
            "metrics_detail": json.dumps(metrics_detail, ensure_ascii=False),
        },
    )


def keep_current_model():
    print("Candidate model did not beat active model by AUC-PR.")


with DAG(
    dag_id="dag_retrain_model",
    default_args=default_args,
    description="DAG 3: weekly model retraining with model registry.",
    schedule_interval="0 6 * * 0",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["tiki", "ml", "retrain"],
) as dag:
    branch_data = BranchPythonOperator(task_id="check_data_sufficiency", python_callable=check_data_sufficiency)
    skip = EmptyOperator(task_id="skip_retrain")
    train = PythonOperator(task_id="train_and_evaluate", python_callable=train_and_evaluate)
    branch_model = BranchPythonOperator(task_id="compare_and_decide", python_callable=compare_and_decide)
    deploy = PythonOperator(task_id="deploy_new_model", python_callable=deploy_new_model)
    keep = PythonOperator(task_id="keep_current_model", python_callable=keep_current_model)

    branch_data >> [skip, train]
    train >> branch_model >> [deploy, keep]
