from __future__ import annotations

from CRAWLER.crawlers.product_crawler import ProductCrawler
from CRAWLER.crawlers.review_crawler import ReviewCrawler
from CRAWLER.crawlers.user_crawler import UserCrawler


def test_product_normalization_builds_absolute_url():
    product = ProductCrawler._normalize_product(
        {
            "id": 123,
            "name": "Điện thoại demo",
            "brand": {"name": "DemoBrand"},
            "rating_average": 4.7,
            "review_count": 12,
            "url_path": "dien-thoai-demo-p123.html",
        },
        "dien-thoai",
    )

    assert product["product_id"] == "123"
    assert product["url"] == "https://tiki.vn/dien-thoai-demo-p123.html"


def test_keyword_discovery_sorts_and_skips_completed_products():
    class DummyProductCrawler(ProductCrawler):
        def search_products(self, keyword: str, max_pages: int = 3, limit: int = 40):
            return [
                {"product_id": "done", "sold_count": 999, "review_count": 50, "name": "Done"},
                {"product_id": "low", "sold_count": 1, "review_count": 100, "name": "Low"},
                {"product_id": "top", "sold_count": 20, "review_count": 2, "name": "Top"},
            ]

    products = DummyProductCrawler(delay_range=(0, 0)).discover_top_products_by_keyword(
        ["điện thoại"],
        products_per_keyword=2,
        excluded_product_ids={"done"},
    )

    assert [product["product_id"] for product in products] == ["top", "low"]
    assert products[0]["discovery_keyword"] == "điện thoại"


def test_product_normalization_does_not_use_sold_count_as_review_count():
    product = ProductCrawler._normalize_product(
        {
            "id": 123,
            "name": "Điện thoại demo",
            "quantity_sold": {"text": "Đã bán 431", "value": 431},
        },
        "điện thoại",
    )

    assert product["sold_count"] == 431
    assert product["review_count"] == 0


def test_review_normalization_keeps_user_context():
    review = ReviewCrawler._normalize_review(
        {
            "id": 99,
            "rating": 5,
            "content": "Sản phẩm tốt, giao nhanh",
            "created_at": 1_700_000_000,
            "created_by": {"id": 42, "name": "User", "reviews_count": 2},
            "is_buyer": True,
        },
        "123",
    )

    assert review["review_id"] == "99"
    assert review["user_id"] == "42"
    assert review["total_reviews"] == 2
    assert review["purchased"] is True


def test_crawl_product_reviews_skips_empty_comments():
    class DummyReviewCrawler(ReviewCrawler):
        def get_json(self, path, params=None):
            return {
                "data": [
                    {"id": 1, "rating": 5, "content": "", "created_by": {"id": 42}},
                    {"id": 2, "rating": 4, "content": "Nội dung review thật", "created_by": {"id": 43}},
                ]
            }

    reviews = DummyReviewCrawler(delay_range=(0, 0)).crawl_product_reviews("123", max_pages=1)

    assert len(reviews) == 1
    assert reviews[0]["review_id"] == "2"


def test_crawl_product_reviews_can_follow_all_pages():
    class DummyReviewCrawler(ReviewCrawler):
        def get_json(self, path, params=None):
            page = params["page"]
            return {
                "paging": {"last_page": 2},
                "data": [
                    {"id": page, "rating": 4, "content": f"Nội dung trang {page}", "created_by": {"id": page}},
                ],
            }

    reviews = DummyReviewCrawler(delay_range=(0, 0)).crawl_product_reviews("123", max_pages=1, crawl_all_pages=True)

    assert [review["review_id"] for review in reviews] == ["1", "2"]


def test_user_normalization_parses_timestamp():
    user = UserCrawler._normalize_user({"id": 42, "created_at": 1_700_000_000, "reviews_count": 7}, "42")

    assert user["user_id"] == "42"
    assert user["join_date"] is not None
    assert user["total_reviews"] == 7
