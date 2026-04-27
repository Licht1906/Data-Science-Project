"""
analyzer.py — Service layer: điều phối crawler + model → kết quả phân tích.
Tách khỏi route để dễ test và tái sử dụng.
"""
import re
from datetime import datetime
from typing import Any
from app.schemas.tiki import TikiAnalyzeResponse, ProductSummary, ReviewResult


def extract_product_id(url: str) -> str:
    """Trích product_id từ URL dạng ...p{id}.html"""
    match = re.search(r"-p(\d+)\.html", url)
    if match:
        return match.group(1)
    raise ValueError(f"Không trích được product_id từ URL: {url}")


def compute_risk_level(fake_ratio: float) -> str:
    if fake_ratio < 0.1:
        return "LOW"
    elif fake_ratio < 0.3:
        return "MEDIUM"
    return "HIGH"


class TikiAnalyzerService:
    def __init__(self, crawler: Any, model: Any):
        self.crawler = crawler
        self.model = model

    def analyze(self, url: str) -> TikiAnalyzeResponse:
        product_id = extract_product_id(url)

        # 1. Thu thập review
        raw_reviews = self.crawler.fetch_reviews(product_id)
        if not raw_reviews:
            return None

        # 2. Dự đoán
        review_results = []
        for r in raw_reviews:
            prob, flags = self._predict(r)
            review_results.append(ReviewResult(
                review_id=str(r.get("id", "")),
                content=r.get("content", ""),
                rating=int(r.get("rating", 0)),
                fake_probability=round(prob, 4),
                is_fake=prob >= 0.5,
                flags=flags,
                reviewer=r.get("created_by", {}).get("name") if r.get("created_by") else None,
                created_at=r.get("created_at"),
            ))

        # 3. Tổng hợp
        fake_count = sum(1 for r in review_results if r.is_fake)
        total = len(review_results)
        fake_ratio = fake_count / total if total > 0 else 0.0
        avg_rating = sum(r.rating for r in review_results) / total if total > 0 else 0.0

        product = ProductSummary(
            product_id=product_id,
            product_name=raw_reviews[0].get("product_name", f"Sản phẩm {product_id}"),
            total_reviews=total,
            fake_count=fake_count,
            fake_ratio=round(fake_ratio, 4),
            avg_rating=round(avg_rating, 2),
            risk_level=compute_risk_level(fake_ratio),
        )

        return TikiAnalyzeResponse(
            product=product,
            reviews=review_results,
            analyzed_at=datetime.utcnow(),
            model_version=getattr(self.model, "version", "unknown"),
        )

    def _predict(self, review: dict) -> tuple[float, list[str]]:
        """
        Trả về (xác suất fake, danh sách cờ heuristic).
        Khi N5 cung cấp feature_engineering, thay phần này.
        """
        # TODO: thay bằng feature engineering thật từ N5
        # features = build_features(review)
        # prob = self.model.predict_proba([features])[0][1]

        # Hiện tại dùng heuristic đơn giản (stub)
        flags = []
        content = review.get("content", "")
        rating = int(review.get("rating", 3))

        if rating in (1, 5):
            flags.append("extreme_rating")
        if len(content) < 20:
            flags.append("short_content")
        if not review.get("purchased"):
            flags.append("not_verified_purchase")

        prob = min(0.3 * len(flags), 1.0)
        return prob, flags