import os
from functools import lru_cache
from typing import Any

MODEL_PATH = os.getenv("MODEL_PATH", "models/fake_review_model.pkl")


class MockModel:
    """Model giả dùng khi N5 chưa cung cấp file .pkl."""
    version = "mock-v1"


def get_model() -> Any:
    """FastAPI dependency: trả về model.
    TODO: khi N5 xong → đổi thành load_model()
    """
    return MockModel()


def get_review_crawler():
    """FastAPI dependency: trả về crawler.
    TODO: khi N3 xong → import ReviewCrawler thật
    """
    from app.services.mock_crawler import MockReviewCrawler
    return MockReviewCrawler()