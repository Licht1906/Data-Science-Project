from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from sqlalchemy import create_engine

from CRAWLER.keywords_env import tiki_keywords_from_env
from db_schema_compat import read_model_registry


def render_crawler_dashboard() -> None:
    st.header("Tiki Auto Crawler")
    st.caption("Theo dõi keyword discovery, sản phẩm đã crawl, comment thật và dữ liệu sau preprocessing.")

    engine = create_engine(os.getenv("TIKI_DATA_DB", "postgresql+psycopg2://airflow:airflow@localhost:5432/tiki_data"))
    try:
        with engine.connect() as conn:
            products = pd.read_sql(
                """
                SELECT product_id, name, category, price, brand, rating_avg, review_count, url, crawled_at
                FROM raw_products
                ORDER BY crawled_at DESC
                """,
                conn,
            )
            reviews = pd.read_sql(
                """
                SELECT review_id, product_id, user_id, rating, content, helpful_count, purchased, created_at, crawled_at
                FROM raw_reviews
                ORDER BY crawled_at DESC
                """,
                conn,
            )
            history = pd.read_sql(
                """
                SELECT keyword, product_id, status, selected_at, completed_at, review_count
                FROM crawl_product_history
                ORDER BY selected_at DESC
                """,
                conn,
            )
            processed = pd.read_sql(
                """
                SELECT
                    pr.review_id,
                    pr.product_id,
                    pr.user_id,
                    pr.rating,
                    pr.content_clean,
                    pr.is_fake,
                    pr.fake_probability,
                    pr.flag_count,
                    pr.flags,
                    pr.label_version,
                    pr.processed_at,
                    r.content AS raw_content,
                    r.helpful_count,
                    r.purchased,
                    r.created_at AS review_created_at,
                    p.category,
                    p.name AS product_name,
                    u.total_reviews,
                    u.avg_rating_given
                FROM processed_reviews pr
                LEFT JOIN raw_reviews r ON pr.review_id = r.review_id
                LEFT JOIN raw_products p ON pr.product_id = p.product_id
                LEFT JOIN raw_users u ON pr.user_id = u.user_id
                ORDER BY pr.processed_at DESC
                """,
                conn,
            )
        model_registry = read_model_registry(engine)
    except Exception as exc:
        st.error(f"Chưa kết nối được PostgreSQL hoặc schema crawl chưa sẵn sàng: {exc}")
        return

    _render_metrics(products, reviews, history, processed, keywords_configured=tiki_keywords_from_env())

    crawl_tab, keyword_tab, review_tab, preprocessing_tab, model_tab = st.tabs(
        ["Crawl Overview", "Keyword History", "Comments", "Preprocessing", "Model registry"]
    )
    with crawl_tab:
        _render_crawl_overview(products, reviews)
    with keyword_tab:
        _render_keyword_history(history)
    with review_tab:
        _render_reviews(reviews)
    with preprocessing_tab:
        _render_preprocessing(processed)
    with model_tab:
        _render_model_registry(model_registry)


def _render_model_registry(registry: pd.DataFrame) -> None:
    st.subheader("Lịch sử train & đánh giá")
    st.caption(
        "Mỗi lần `dag_retrain_model` deploy thành công ghi một dòng vào `model_registry`; "
        "cột `metrics_detail` lưu AUC-PR/F1/AUC-ROC và threshold của tất cả mô hình candidate."
    )
    missing = registry.attrs.get("missing_registry_columns") or []
    if missing:
        st.warning(
            "PostgreSQL đang dùng `model_registry` phiên bản cũ (thiếu cột: **"
            + ", ".join(missing)
            + "**). Chạy một lần file migration `DS/migrations/001_extend_model_registry.sql` "
            "hoặc `ALTER TABLE` tương đương rồi F5 trang."
        )
    if registry.empty:
        st.info("Chưa có lần train nào ghi vào DB. Chạy DAG `dag_retrain_model` (NEXT_STEP) sau khi đủ dữ liệu trong `processed_reviews`.")
        return
    display = registry.drop(columns=["metrics_detail"], errors="ignore")
    st.dataframe(display, use_container_width=True)
    if not registry.empty and "auc_pr" in registry.columns:
        reg = registry.copy()
        reg["trained_at"] = pd.to_datetime(reg["trained_at"], errors="coerce")
        reg_sorted = reg.sort_values("trained_at")
        line_kw: dict = {
            "data_frame": reg_sorted,
            "x": "trained_at",
            "y": "auc_pr",
            "markers": True,
            "title": "AUC-PR theo lần train",
        }
        if "model_name" in reg_sorted.columns and reg_sorted["model_name"].notna().any():
            line_kw["color"] = "model_name"
        st.plotly_chart(px.line(**line_kw), use_container_width=True)
    for _, row in registry.head(5).iterrows():
        detail = row.get("metrics_detail")
        if detail is None or (isinstance(detail, float) and pd.isna(detail)):
            continue
        title = f"Chi tiết run #{row.get('model_id')} — {row.get('model_name') or 'model'} ({row.get('trained_at')})"
        with st.expander(title):
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except json.JSONDecodeError:
                    st.code(detail)
                    continue
            st.json(detail)


def _render_metrics(
    products: pd.DataFrame,
    reviews: pd.DataFrame,
    history: pd.DataFrame,
    processed: pd.DataFrame,
    *,
    keywords_configured: list[str],
) -> None:
    keywords_in_db = int(history["keyword"].nunique()) if not history.empty else 0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Products", len(products))
    col2.metric("Comments", len(reviews))
    col3.metric(
        "Keywords (cấu hình)",
        len(keywords_configured),
        delta=f"{keywords_in_db} đã vào DB",
        delta_color="off",
        help="Số keyword trong TIKI_KEYWORDS / JSON (Streamlit và Airflow có thể khác nhau nếu .env chỉ được load một bên). "
        f"'đã vào DB' = số keyword khác nhau trong crawl_product_history (sản phẩm đã từng được chọn).",
    )
    col4.metric("Processed", len(processed))


def _render_crawl_overview(products: pd.DataFrame, reviews: pd.DataFrame) -> None:
    if products.empty:
        st.info("Chưa có sản phẩm crawl. Hãy chạy Airflow DAG `dag_crawl_tiki` hoặc crawler script.")
        return
    products["crawled_at"] = pd.to_datetime(products["crawled_at"], errors="coerce")
    st.plotly_chart(px.histogram(products, x="category", title="Số sản phẩm theo keyword/category"), use_container_width=True)
    if not reviews.empty:
        rv = reviews.copy()
        rv["crawled_at"] = pd.to_datetime(rv["crawled_at"], errors="coerce")
        rv["created_at"] = pd.to_datetime(rv["created_at"], errors="coerce")
        by_crawl = rv.dropna(subset=["crawled_at"])
        if by_crawl.empty:
            st.warning("Không có `crawled_at` hợp lệ cho comment — kiểm tra dữ liệu raw_reviews.")
        else:
            daily_crawl = (
                by_crawl.assign(day=by_crawl["crawled_at"].dt.normalize())
                .groupby("day", as_index=False)
                .size()
                .rename(columns={"size": "comments"})
            )
            st.plotly_chart(
                px.line(daily_crawl, x="day", y="comments", markers=True, title="Comment ghi vào DB theo ngày (crawled_at)"),
                use_container_width=True,
            )
            st.caption(
                "`crawled_at` là lần đầu ghi review vào DB. Trước đây upsert đã cập nhật trường này mỗi lần crawl nên biểu đồ chỉ nhìn thấy ngày mới nhất; pipeline đã sửa để giữ lịch sử."
            )
        by_tiki = rv.dropna(subset=["created_at"])
        if not by_tiki.empty:
            daily_created = (
                by_tiki.assign(day=by_tiki["created_at"].dt.normalize())
                .groupby("day", as_index=False)
                .size()
                .rename(columns={"size": "comments"})
            )
            st.plotly_chart(
                px.line(
                    daily_created,
                    x="day",
                    y="comments",
                    markers=True,
                    title="Reviews theo ngày đăng trên Tiki (created_at)",
                ),
                use_container_width=True,
            )
        else:
            st.caption("Cột `created_at` trống hoặc không đọc được — chỉ có biểu đồ crawl.")
        st.plotly_chart(px.histogram(rv, x="rating", color="purchased", title="Phân phối rating của comment thật"), use_container_width=True)
    st.dataframe(products, use_container_width=True)


def _render_keyword_history(history: pd.DataFrame) -> None:
    if history.empty:
        st.info("Chưa có lịch sử keyword crawl.")
        return
    st.plotly_chart(px.histogram(history, x="keyword", color="status", title="Trạng thái crawl theo keyword"), use_container_width=True)
    st.dataframe(history, use_container_width=True)


def _render_reviews(reviews: pd.DataFrame) -> None:
    if reviews.empty:
        st.info("Chưa có comment thật trong `raw_reviews`.")
        return
    reviews["content_length"] = reviews["content"].fillna("").str.len()
    st.plotly_chart(px.histogram(reviews, x="content_length", nbins=30, title="Độ dài comment"), use_container_width=True)
    st.dataframe(reviews, use_container_width=True)
    st.download_button(
        "Tải raw comments CSV",
        data=reviews.to_csv(index=False).encode("utf-8-sig"),
        file_name="tiki_raw_comments.csv",
        mime="text/csv",
    )


def _render_preprocessing(processed: pd.DataFrame) -> None:
    if processed.empty:
        st.info("Chưa có dữ liệu preprocessing. Hãy chạy DAG `dag_clean_label` sau khi crawl.")
        return
    data = _prepare_processed_visual_data(processed)
    _render_preprocessing_metrics(data)
    st.plotly_chart(_build_preprocessing_subplot(data), use_container_width=True)

    flag_counts = _explode_flag_counts(data)
    if not flag_counts.empty:
        st.plotly_chart(
            px.bar(
                flag_counts,
                x="flag",
                y="count",
                color="flag",
                title="Tần suất từng heuristic flag",
                labels={"flag": "Heuristic flag", "count": "Số review"},
            ),
            use_container_width=True,
        )

    columns = [
        "review_id",
        "product_id",
        "category",
        "rating",
        "content_clean",
        "content_word_count",
        "is_fake",
        "fake_probability",
        "flag_count",
        "flags",
        "purchased",
        "helpful_count",
        "review_created_at",
        "processed_at",
    ]
    st.dataframe(data[[column for column in columns if column in data.columns]], use_container_width=True)
    st.download_button(
        "Tải processed reviews CSV",
        data=data.to_csv(index=False).encode("utf-8-sig"),
        file_name="tiki_processed_reviews.csv",
        mime="text/csv",
    )


def _prepare_processed_visual_data(processed: pd.DataFrame) -> pd.DataFrame:
    data = processed.copy()
    data["label"] = data["is_fake"].map({0: "Bình thường", 1: "Nghi vấn"}).fillna("Không rõ")
    data["rating"] = pd.to_numeric(data.get("rating"), errors="coerce")
    data["flag_count"] = pd.to_numeric(data.get("flag_count"), errors="coerce").fillna(0)
    data["fake_probability"] = pd.to_numeric(data.get("fake_probability"), errors="coerce")
    data["helpful_count"] = pd.to_numeric(data.get("helpful_count"), errors="coerce").fillna(0)
    data["total_reviews"] = pd.to_numeric(data.get("total_reviews"), errors="coerce").fillna(0)
    data["content_clean"] = data.get("content_clean", pd.Series(dtype=str)).fillna("")
    data["content_char_count"] = data["content_clean"].str.len()
    data["content_word_count"] = data["content_clean"].str.split().str.len().fillna(0)
    data["processed_at"] = pd.to_datetime(data.get("processed_at"), errors="coerce")
    data["review_created_at"] = pd.to_datetime(data.get("review_created_at"), errors="coerce")
    data["category"] = data.get("category", pd.Series(dtype=str)).fillna("unknown")
    return data


def _render_preprocessing_metrics(data: pd.DataFrame) -> None:
    suspicious_rate = float(data["is_fake"].mean() or 0)
    median_words = float(data["content_word_count"].median() or 0)
    avg_flags = float(data["flag_count"].mean() or 0)
    label_versions = ", ".join(sorted(map(str, data["label_version"].dropna().unique()))) if "label_version" in data else "n/a"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Processed reviews", len(data))
    col2.metric("Tỷ lệ nghi vấn", f"{suspicious_rate:.1%}")
    col3.metric("Median words", f"{median_words:.0f}")
    col4.metric("Avg flags", f"{avg_flags:.2f}", help=f"Label version: {label_versions}")


def _build_preprocessing_subplot(data: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3,
        cols=2,
        subplot_titles=(
            "Tỷ lệ nhãn heuristic",
            "Phân phối số flag",
            "Độ dài comment sau clean",
            "Rating theo nhãn",
            "Top category có review nghi vấn",
            "Review theo ngày đăng Tiki",
        ),
        specs=[
            [{"type": "domain"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.09,
    )

    label_counts = data["label"].value_counts()
    fig.add_trace(go.Pie(labels=label_counts.index, values=label_counts.values, hole=0.45), row=1, col=1)

    for label, subset in data.groupby("label"):
        fig.add_trace(go.Histogram(x=subset["flag_count"], name=label, opacity=0.72), row=1, col=2)
        fig.add_trace(go.Box(y=subset["content_word_count"], name=label, boxmean=True), row=2, col=1)
        fig.add_trace(go.Histogram(x=subset["rating"], name=label, opacity=0.72, showlegend=False), row=2, col=2)

    suspicious_by_category = (
        data.assign(is_suspicious=data["is_fake"].astype(int))
        .groupby("category", as_index=False)
        .agg(reviews=("review_id", "count"), suspicious=("is_suspicious", "sum"))
    )
    suspicious_by_category["suspicious_rate"] = suspicious_by_category["suspicious"] / suspicious_by_category["reviews"].clip(lower=1)
    suspicious_by_category = suspicious_by_category.sort_values(["suspicious", "suspicious_rate"], ascending=False).head(10)
    fig.add_trace(
        go.Bar(
            x=suspicious_by_category["category"],
            y=suspicious_by_category["suspicious"],
            customdata=suspicious_by_category[["reviews", "suspicious_rate"]],
            hovertemplate="Category=%{x}<br>Nghi vấn=%{y}<br>Total=%{customdata[0]}<br>Rate=%{customdata[1]:.1%}<extra></extra>",
            name="Nghi vấn/category",
        ),
        row=3,
        col=1,
    )

    timeline = (
        data.dropna(subset=["review_created_at"])
        .assign(day=lambda frame: frame["review_created_at"].dt.normalize())
        .groupby(["day", "label"], as_index=False)
        .size()
        .rename(columns={"size": "reviews"})
    )
    for label, subset in timeline.groupby("label"):
        fig.add_trace(go.Scatter(x=subset["day"], y=subset["reviews"], mode="lines+markers", name=f"{label} theo ngày"), row=3, col=2)

    fig.update_layout(
        title="EDA sau preprocessing và gán nhãn heuristic",
        barmode="overlay",
        height=950,
        legend_title_text="Nhãn",
    )
    fig.update_xaxes(title_text="Flag count", row=1, col=2)
    fig.update_yaxes(title_text="Số review", row=1, col=2)
    fig.update_yaxes(title_text="Số từ", row=2, col=1)
    fig.update_xaxes(title_text="Rating", row=2, col=2)
    fig.update_yaxes(title_text="Số review", row=2, col=2)
    fig.update_xaxes(title_text="Category", row=3, col=1)
    fig.update_yaxes(title_text="Review nghi vấn", row=3, col=1)
    fig.update_xaxes(title_text="Ngày đăng", row=3, col=2)
    fig.update_yaxes(title_text="Số review", row=3, col=2)
    return fig


def _explode_flag_counts(data: pd.DataFrame) -> pd.DataFrame:
    counter: Counter[str] = Counter()
    for value in data.get("flags", []):
        for flag in _coerce_flags(value):
            counter[flag] += 1
    return pd.DataFrame(counter.items(), columns=["flag", "count"]).sort_values("count", ascending=False)


def _coerce_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if pd.isna(value):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            import json

            parsed = json.loads(stripped)
        except ValueError:
            return [stripped]
        return _coerce_flags(parsed)
    return []
