"""Đọc danh sách keyword Tiki từ biến môi trường (dùng chung cho DAG Airflow và Streamlit)."""

from __future__ import annotations

import json
import os

from CRAWLER.crawlers.product_crawler import DEFAULT_KEYWORDS


def tiki_keywords_from_env() -> list[str]:
    raw_json = os.getenv("TIKI_KEYWORDS_JSON")
    if raw_json:
        parsed = json.loads(raw_json)
        return [str(keyword).strip() for keyword in parsed if str(keyword).strip()]
    raw = os.getenv("TIKI_KEYWORDS", ",".join(DEFAULT_KEYWORDS))
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]
