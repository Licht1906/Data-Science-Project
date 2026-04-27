"""
tests/test_api.py — Test tự động cho N2.
Chạy: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app
from app.deps import get_model, get_review_crawler
from app.services.mock_crawler import MockReviewCrawler


# ---------- Fixtures ----------

def mock_model():
    model = MagicMock()
    model.version = "test-v1"
    return model


def mock_crawler():
    return MockReviewCrawler()


# Override dependencies
app.dependency_overrides[get_model] = mock_model
app.dependency_overrides[get_review_crawler] = mock_crawler

client = TestClient(app)


# ---------- /health ----------

def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_has_required_fields():
    response = client.get("/health")
    data = response.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


# ---------- POST /analyze/tiki — Happy path ----------

VALID_URL = "https://tiki.vn/dien-thoai-demo-p123456.html"


def test_analyze_tiki_returns_200():
    response = client.post("/analyze/tiki", json={"url": VALID_URL})
    assert response.status_code == 200


def test_analyze_tiki_response_structure():
    response = client.post("/analyze/tiki", json={"url": VALID_URL})
    data = response.json()
    assert "product" in data
    assert "reviews" in data
    assert "analyzed_at" in data

    product = data["product"]
    assert "product_id" in product
    assert "total_reviews" in product
    assert "fake_ratio" in product
    assert "risk_level" in product
    assert product["risk_level"] in ("LOW", "MEDIUM", "HIGH")


def test_analyze_tiki_reviews_have_required_fields():
    response = client.post("/analyze/tiki", json={"url": VALID_URL})
    reviews = response.json()["reviews"]
    assert len(reviews) > 0
    for r in reviews:
        assert "review_id" in r
        assert "fake_probability" in r
        assert 0.0 <= r["fake_probability"] <= 1.0
        assert "is_fake" in r
        assert "flags" in r


# ---------- POST /analyze/tiki — Lỗi ----------

def test_analyze_tiki_invalid_url_returns_400():
    response = client.post("/analyze/tiki", json={"url": "https://shopee.vn/product/123"})
    assert response.status_code == 400


def test_analyze_tiki_no_url_returns_422():
    response = client.post("/analyze/tiki", json={})
    assert response.status_code == 422


def test_analyze_tiki_empty_url_returns_400():
    response = client.post("/analyze/tiki", json={"url": "not-a-url"})
    assert response.status_code == 400