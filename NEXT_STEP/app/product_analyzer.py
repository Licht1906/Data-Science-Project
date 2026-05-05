from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


def render_product_analyzer() -> None:
    st.header("Tiki Review Analyzer")
    st.caption("Nhập URL sản phẩm Tiki để xem tỷ lệ review đáng nghi và các cờ heuristic.")

    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    product_url = st.text_input(
        "URL sản phẩm Tiki",
        "https://tiki.vn/sach-sach-la-hoa-tren-duong-ve-sa-mon-thich-phap-hoa-tang-kem-ngau-nhien-1-la-bo-de-p279148199.html?spid=279148200",
    )
    max_pages = st.slider("Số trang review cần crawl", min_value=1, max_value=10, value=2)
    use_live_crawl = st.checkbox("Crawl live từ Tiki", value=False)

    if st.button("Phân tích", type="primary"):
        with st.spinner("Đang gọi API phân tích..."):
            response = requests.post(
                f"{api_base_url}/analyze/tiki",
                json={"product_url": product_url, "max_pages": max_pages, "use_live_crawl": use_live_crawl},
                timeout=60,
            )
        if response.status_code != 200:
            st.error(response.text)
            return
        payload = response.json()
        if payload.get("crawl_status") == "fallback":
            st.warning(payload.get("crawl_message") or "Không crawl được dữ liệu live, đang dùng fallback.")
        _render_result(payload)


def _render_result(payload: dict) -> None:
    left, mid, right = st.columns(3)
    left.metric("Tổng review", payload["total_reviews"])
    mid.metric("Review đáng nghi", payload["suspicious_reviews"])
    right.metric("Tỷ lệ đáng nghi", f"{payload['fake_rate']:.1%}")
    st.progress(min(float(payload["average_fake_probability"]), 1.0), text="Xác suất fake trung bình")

    reviews_df = pd.DataFrame(payload["reviews"])
    if not reviews_df.empty:
        chart_left, chart_right = st.columns(2)
        chart_left.plotly_chart(
            px.histogram(reviews_df, x="fake_probability", nbins=10, title="Phân phối xác suất fake"),
            use_container_width=True,
        )
        chart_right.plotly_chart(
            px.scatter(
                reviews_df,
                x="rating",
                y="fake_probability",
                color="is_suspicious",
                hover_data=["review_id", "flags"],
                title="Rating vs xác suất fake",
            ),
            use_container_width=True,
        )
        flag_counts = reviews_df.explode("flags")
        flag_counts = flag_counts[flag_counts["flags"].notna() & (flag_counts["flags"] != "")]
        if not flag_counts.empty:
            st.plotly_chart(px.histogram(flag_counts, x="flags", title="Tần suất heuristic flags"), use_container_width=True)
        st.download_button(
            "Tải kết quả CSV",
            data=reviews_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"tiki_analysis_{payload['product_id']}.csv",
            mime="text/csv",
        )

    for review in payload["reviews"]:
        status = "Đáng nghi" if review["is_suspicious"] else "Bình thường"
        with st.container(border=True):
            st.subheader(f"{status} · {review['fake_probability']:.1%}")
            st.write(review["content"])
            st.caption(f"Rating: {review['rating']} · Flags: {', '.join(review['flags']) or 'Không có'}")
