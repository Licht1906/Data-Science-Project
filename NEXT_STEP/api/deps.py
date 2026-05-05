from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from crawlers.review_crawler import ReviewCrawler
from src.modeling import load_model


@lru_cache(maxsize=1)
def get_review_crawler() -> ReviewCrawler:
    return ReviewCrawler(
        delay_range=(
            float(os.getenv("CRAWLER_DELAY_MIN", "1")),
            float(os.getenv("CRAWLER_DELAY_MAX", "3")),
        ),
        retries=int(os.getenv("CRAWLER_RETRIES", "3")),
        timeout=int(os.getenv("CRAWLER_TIMEOUT", "20")),
    )


@lru_cache(maxsize=1)
def get_model_bundle():
    model_path = Path(os.getenv("MODEL_PATH", "models/xgb_model.pkl"))
    if not model_path.exists():
        return None
    return load_model(model_path)
