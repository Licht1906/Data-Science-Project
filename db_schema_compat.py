"""Đọc bảng model_registry tương thích schema cũ (thiếu model_name, threshold, metrics_detail)."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

MODEL_REGISTRY_COLUMNS_PREFERRED: tuple[str, ...] = (
    "model_id",
    "model_path",
    "model_name",
    "auc_pr",
    "f1_score",
    "auc_roc",
    "threshold",
    "n_train",
    "fake_rate",
    "metrics_path",
    "metrics_detail",
    "is_active",
    "trained_at",
    "notes",
)


def read_model_registry(engine: Engine) -> pd.DataFrame:
    insp = inspect(engine)
    if not insp.has_table("model_registry"):
        return _empty_registry()

    present = {c["name"] for c in insp.get_columns("model_registry")}
    cols = [c for c in MODEL_REGISTRY_COLUMNS_PREFERRED if c in present]
    if not cols:
        return _empty_registry()

    quoted = ", ".join(cols)
    df = pd.read_sql(f"SELECT {quoted} FROM model_registry ORDER BY trained_at DESC", engine)
    for name in MODEL_REGISTRY_COLUMNS_PREFERRED:
        if name not in df.columns:
            df[name] = pd.NA

    missing = [c for c in MODEL_REGISTRY_COLUMNS_PREFERRED if c not in present]
    df.attrs["missing_registry_columns"] = missing
    return df


def _empty_registry() -> pd.DataFrame:
    return pd.DataFrame(columns=list(MODEL_REGISTRY_COLUMNS_PREFERRED))
