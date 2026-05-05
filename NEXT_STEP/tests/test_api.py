from __future__ import annotations

from fastapi.testclient import TestClient

from api.deps import get_model_bundle, get_review_crawler
from api.main import app


class DummyCrawler:
    def crawl_product_reviews(self, product_id: str, max_pages: int = 2):
        return [
            {
                "review_id": "r1",
                "product_id": product_id,
                "user_id": "u1",
                "rating": 5,
                "content": "Sản phẩm tốt",
                "helpful_count": 0,
                "purchased": False,
                "total_reviews": 1,
            }
        ]


class FailingCrawler:
    def crawl_product_reviews(self, product_id: str, max_pages: int = 2):
        raise RuntimeError("Cannot fetch https://tiki.vn/api/v2/reviews")


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_tiki_uses_contract():
    app.dependency_overrides[get_review_crawler] = lambda: DummyCrawler()
    app.dependency_overrides[get_model_bundle] = lambda: None
    client = TestClient(app)

    response = client.post(
        "/analyze/tiki",
        json={"product_url": "https://tiki.vn/demo-p123456.html", "max_pages": 1, "use_live_crawl": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "123456"
    assert payload["total_reviews"] == 1
    assert payload["reviews"][0]["is_suspicious"] is True

    app.dependency_overrides.clear()


def test_analyze_tiki_falls_back_when_live_crawl_fails():
    app.dependency_overrides[get_review_crawler] = lambda: FailingCrawler()
    app.dependency_overrides[get_model_bundle] = lambda: None
    client = TestClient(app)

    response = client.post(
        "/analyze/tiki",
        json={"product_url": "https://tiki.vn/demo-p123456.html", "max_pages": 1, "use_live_crawl": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "123456"
    assert payload["total_reviews"] == 2
    assert payload["model_version"] == "heuristic_fallback"

    app.dependency_overrides.clear()
