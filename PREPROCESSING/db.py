from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_database_url() -> str:
    """URL dùng chung cho Streamlit, script và (ưu tiên) DAG preprocessing.

    Airflow Connection `tiki_data` có thể lệch với `.env` nếu không chạy lại `airflow-init`
    sau khi đổi Neon — DAG `dag_clean_label` nên dùng hàm này thay vì chỉ PostgresHook.
    """
    return os.getenv("TIKI_DATA_DB", "postgresql+psycopg2://airflow:airflow@localhost:5432/tiki_data")


def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


@contextmanager
def db_connection() -> Iterator:
    engine = get_engine()
    with engine.begin() as connection:
        yield connection
