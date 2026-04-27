"""
mock_crawler.py — Crawler giả để N2 phát triển & test độc lập khi N3 chưa xong.
Trả về dữ liệu tĩnh mô phỏng response thật từ Tiki.
"""
import random


MOCK_REVIEWS = [
    {
        "id": "rv_001", "content": "Sản phẩm tốt lắm, giao hàng nhanh, đóng gói cẩn thận!",
        "rating": 5, "purchased": True,
        "created_by": {"name": "Nguyễn Văn A"}, "created_at": "2024-01-15T10:30:00Z",
        "product_name": "Điện thoại Demo X1",
    },
    {
        "id": "rv_002", "content": "ok",
        "rating": 5, "purchased": False,
        "created_by": {"name": "user_ghost_99"}, "created_at": "2024-01-16T02:00:00Z",
        "product_name": "Điện thoại Demo X1",
    },
    {
        "id": "rv_003", "content": "Hàng kém chất lượng, không như mô tả, rất thất vọng.",
        "rating": 1, "purchased": True,
        "created_by": {"name": "Trần Thị B"}, "created_at": "2024-01-17T14:00:00Z",
        "product_name": "Điện thoại Demo X1",
    },
    {
        "id": "rv_004", "content": "Bình thường, dùng tạm được.",
        "rating": 3, "purchased": True,
        "created_by": {"name": "Lê Văn C"}, "created_at": "2024-01-18T09:00:00Z",
        "product_name": "Điện thoại Demo X1",
    },
    {
        "id": "rv_005", "content": "Tuyệt vời",
        "rating": 5, "purchased": False,
        "created_by": None, "created_at": "2024-01-19T22:00:00Z",
        "product_name": "Điện thoại Demo X1",
    },
]


class MockReviewCrawler:
    """Dùng trong dev/test. Thay bằng ReviewCrawler thật khi N3 hoàn thiện."""

    def fetch_reviews(self, product_id: str, max_pages: int = 5) -> list[dict]:
        # Trả về mock data cố định (không crawl thật)
        return MOCK_REVIEWS