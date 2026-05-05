from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

_DS_ROOT = Path(__file__).resolve().parents[2]
if str(_DS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DS_ROOT))

from db_schema_compat import read_model_registry


def render_dashboard() -> None:
    st.header("Admin Dashboard")
    st.caption("Theo dõi dữ liệu đã crawl, nhãn heuristic và model registry.")

    try:
        engine = create_engine(os.getenv("TIKI_DATA_DB", "postgresql+psycopg2://airflow:airflow@localhost:5432/tiki_data"))
        raw_reviews = pd.read_sql(
            """
            SELECT r.rating, r.product_id, r.user_id, r.content, r.helpful_count, r.purchased, r.created_at, r.crawled_at,
                   p.name AS product_name, p.category, p.review_count AS product_review_count
            FROM raw_reviews r
            LEFT JOIN raw_products p ON r.product_id = p.product_id
            """,
            engine,
        )
        processed = pd.read_sql(
            """
            SELECT review_id, product_id, user_id, rating, is_fake, fake_probability, flag_count, flags, processed_at
            FROM processed_reviews
            """,
            engine,
        )
        registry = read_model_registry(engine)
    except Exception as exc:
        st.warning(f"Chưa kết nối được PostgreSQL, hiển thị dữ liệu demo. Chi tiết: {exc}")
        raw_reviews, processed, registry = _demo_data()

    col1, col2, col3 = st.columns(3)
    col1.metric("Raw reviews", len(raw_reviews))
    col2.metric("Processed reviews", len(processed))
    col3.metric("Fake rate", f"{processed['is_fake'].mean():.1%}" if not processed.empty else "0.0%")

    overview_tab, quality_tab, product_tab, model_tab = st.tabs(["Tổng quan", "Preprocessing & labels", "Sản phẩm", "Model"])

    with overview_tab:
        if not raw_reviews.empty:
            raw_reviews["crawled_at"] = pd.to_datetime(raw_reviews["crawled_at"], errors="coerce")
            daily = raw_reviews.dropna(subset=["crawled_at"]).groupby(raw_reviews["crawled_at"].dt.date).size().reset_index(name="reviews")
            st.plotly_chart(px.line(daily, x="crawled_at", y="reviews", markers=True, title="Số review crawl theo ngày"), use_container_width=True)
            st.plotly_chart(px.histogram(raw_reviews, x="rating", color="purchased", title="Phân phối rating theo trạng thái đã mua"), use_container_width=True)

    with quality_tab:
        if not processed.empty:
            processed["processed_at"] = pd.to_datetime(processed["processed_at"], errors="coerce")
            st.plotly_chart(px.histogram(processed, x="flag_count", color="is_fake", title="Số cờ heuristic"), use_container_width=True)
            if "fake_probability" in processed:
                st.plotly_chart(px.histogram(processed, x="fake_probability", color="is_fake", title="Phân phối xác suất fake batch"), use_container_width=True)
            flags = processed.explode("flags") if "flags" in processed else pd.DataFrame()
            if not flags.empty:
                flags = flags[flags["flags"].notna() & (flags["flags"] != "")]
                st.plotly_chart(px.histogram(flags, x="flags", color="is_fake", title="Tần suất từng heuristic flag"), use_container_width=True)

    with product_tab:
        if not processed.empty:
            product_summary = (
                processed.groupby("product_id")
                .agg(total_reviews=("review_id", "count"), fake_rate=("is_fake", "mean"), avg_flags=("flag_count", "mean"))
                .reset_index()
                .sort_values("fake_rate", ascending=False)
            )
            st.plotly_chart(
                px.bar(product_summary.head(20), x="product_id", y="fake_rate", hover_data=["total_reviews", "avg_flags"], title="Top sản phẩm có tỷ lệ review đáng nghi"),
                use_container_width=True,
            )
            st.dataframe(product_summary, use_container_width=True)

    with model_tab:
        st.subheader("Model Registry")
        st.caption("Dòng active = mô hình đang phục vụ inference (sau deploy). `metrics_detail`: so sánh LR / RF / XGBoost.")
        missing = registry.attrs.get("missing_registry_columns") or []
        if missing:
            st.warning(
                "Thiếu cột trên DB: **"
                + ", ".join(missing)
                + "**. Chạy `DS/migrations/001_extend_model_registry.sql` trên PostgreSQL."
            )
        summary = registry.drop(columns=["metrics_detail"], errors="ignore") if not registry.empty else registry
        st.dataframe(summary, use_container_width=True)
        if not registry.empty:
            reg = registry.sort_values("trained_at")
            line_kw: dict = {"data_frame": reg, "x": "trained_at", "y": "auc_pr", "markers": True, "title": "AUC-PR theo lần train"}
            if "model_name" in reg.columns and reg["model_name"].notna().any():
                line_kw["color"] = "model_name"
            st.plotly_chart(px.line(**line_kw), use_container_width=True)
            for _, row in registry.head(3).iterrows():
                detail = row.get("metrics_detail")
                if detail is None or pd.isna(detail):
                    continue
                with st.expander(f"metrics_detail — #{row.get('model_id')} {row.get('model_name') or ''}"):
                    payload = detail
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except json.JSONDecodeError:
                            st.code(payload)
                            continue
                    st.json(payload)


def _demo_data():
    raw_reviews = pd.DataFrame(
        {
            "rating": [5, 4, 1, 5, 3],
            "product_id": ["p1", "p1", "p2", "p3", "p2"],
            "user_id": ["u1", "u2", "u3", "u4", "u5"],
            "content": ["Sản phẩm tốt", "Ổn", "Tệ", "Giao nhanh", "Bình thường"],
            "helpful_count": [0, 2, 1, 0, 4],
            "purchased": [False, True, True, False, True],
            "created_at": pd.Timestamp.now(),
            "crawled_at": pd.Timestamp.now(),
            "category": ["demo", "demo", "demo", "demo", "demo"],
        }
    )
    processed = pd.DataFrame(
        {
            "review_id": ["r1", "r2", "r3", "r4", "r5"],
            "product_id": ["p1", "p1", "p2", "p3", "p2"],
            "user_id": ["u1", "u2", "u3", "u4", "u5"],
            "rating": [5, 4, 1, 5, 3],
            "is_fake": [1, 0, 1, 1, 0],
            "fake_probability": [0.75, 0.25, 0.65, 0.8, 0.15],
            "flag_count": [3, 1, 2, 4, 0],
            "flags": [["r_generic_content"], [], ["r_extreme_rating"], ["r_not_verified_purchase"], []],
            "processed_at": pd.Timestamp.now(),
        }
    )
    registry = pd.DataFrame(
        {
            "model_id": [1],
            "model_path": ["models/xgb_model.pkl"],
            "model_name": ["random_forest"],
            "auc_pr": [0.72],
            "f1_score": [0.64],
            "auc_roc": [0.81],
            "threshold": [0.5],
            "n_train": [500],
            "fake_rate": [0.22],
            "metrics_path": ["models/random_forest_metrics.json"],
            "metrics_detail": [None],
            "is_active": [True],
            "trained_at": [pd.Timestamp.now()],
            "notes": ["demo"],
        }
    )
    return raw_reviews, processed, registry
