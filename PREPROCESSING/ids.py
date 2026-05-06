"""Chuẩn hóa review_id giữa raw / processed (CSV, float, leading zero) — Python đồng bộ với biểu thức SQL inline (không cần CREATE FUNCTION)."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

_DUP_ZERO_SUFFIX = re.compile(r"\.0+\Z")


def _review_key_sql_pg(col: str) -> str:
    """Cùng semantics với `canonical_text_id` — dùng trong JOIN / NOT EXISTS (Postgres)."""
    return (
        f"(CASE WHEN btrim({col}) ~ '^[0-9]+(\\.[0]*)?$' "
        f"THEN ((btrim({col})::numeric)::bigint)::text "
        f"ELSE regexp_replace(btrim({col}), '\\.0+$', '') END)"
    )


SQL_DS_REVIEW_KEY_R = _review_key_sql_pg("r.review_id::text")
SQL_DS_REVIEW_KEY_P = _review_key_sql_pg("p.review_id::text")
SQL_DS_REVIEW_KEY_PR = _review_key_sql_pg("pr.review_id::text")


def canonical_text_id(value: object) -> str:
    """
    Khớp với biểu thức SQL `SQL_DS_REVIEW_KEY_*`:
    - chuỗi chỉ gồm số (có thể .000 hoặc leading zero) → bigint dạng text
    - không phải → btrim + bỏ suffix .0+
    """
    if value is None:
        return ""
    if hasattr(value, "item") and not isinstance(value, (bytes, str, dict, list)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, bool):
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):  # type: ignore[arg-type]
            return ""
        if abs(value - int(value)) < 1e-9:
            return str(int(value))
        return str(value).strip()

    s = str(value).strip()
    if not s:
        return ""

    if re.fullmatch(r"[0-9]+(?:\.[0]*)?", s):
        try:
            return str(int(Decimal(s)))
        except (InvalidOperation, ValueError, OverflowError):
            pass

    try:
        d = Decimal(s)
        if d == d.to_integral_value():
            return str(int(d))
    except (InvalidOperation, ValueError, OverflowError):
        pass

    return _DUP_ZERO_SUFFIX.sub("", s)
