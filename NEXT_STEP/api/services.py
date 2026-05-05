from __future__ import annotations

import logging
from statistics import mean

from fastapi import HTTPException

from api.schemas import AnalyzeTikiRequest, AnalyzeTikiResponse, ReviewAnalysis
from crawlers.product_crawler import ProductCrawler
from crawlers.review_crawler import ReviewCrawler
from src.feature_engineering import build_prediction_frame
from src.labeling import label_review
from src.modeling import predict_fake_probability
from src.nlp_utils import clean_text

LOGGER = logging.getLogger(__name__)


def analyze_tiki_product(
    request: AnalyzeTikiRequest,
    crawler: ReviewCrawler,
    model_bundle,
) -> AnalyzeTikiResponse:
    product_url = str(request.product_url)
    product_id = ProductCrawler.product_id_from_url(product_url)
    if not product_id:
        raise HTTPException(status_code=422, detail="URL Tiki không chứa product_id/spid hợp lệ")

    reviews = []
    crawl_status = "demo" if not request.use_live_crawl else "ok"
    crawl_message = None
    live_crawl_failed = False
    if request.use_live_crawl:
        try:
            reviews = crawler.crawl_product_reviews(product_id, max_pages=request.max_pages)
        except RuntimeError as exc:
            LOGGER.warning("Live crawl failed for Tiki product %s; using demo reviews: %s", product_id, exc)
            crawl_status = "fallback"
            crawl_message = "Live crawl từ Tiki thất bại nên API dùng dữ liệu demo để phân tích."
            live_crawl_failed = True
    reviews = [review for review in reviews if clean_text(review.get("content"))]
    if request.use_live_crawl and not reviews and not live_crawl_failed:
        crawl_status = "empty"
        crawl_message = "Crawl live thành công nhưng sản phẩm này chưa có bình luận có nội dung trên Tiki."
    elif not reviews:
        reviews = _demo_reviews(product_id)

    labels = [label_review(review) for review in reviews]

    if model_bundle:
        features = build_prediction_frame([{**review, **label} for review, label in zip(reviews, labels)])
        probabilities = predict_fake_probability(model_bundle, features)
        model_version = model_bundle.get("model_name", "active_model") if isinstance(model_bundle, dict) else "active_model"
        threshold = float(model_bundle.get("threshold", 0.5)) if isinstance(model_bundle, dict) else 0.5
    else:
        probabilities = [min(0.95, 0.15 + label["flag_count"] * 0.2) for label in labels]
        model_version = "heuristic_fallback"
        threshold = 0.5

    analyzed_reviews: list[ReviewAnalysis] = []
    for review, label, probability in zip(reviews, labels, probabilities):
        analyzed_reviews.append(
            ReviewAnalysis(
                review_id=str(review.get("review_id")),
                user_id=str(review.get("user_id") or ""),
                rating=review.get("rating"),
                content=review.get("content") or "",
                content_clean=label["content_clean"],
                fake_probability=round(float(probability), 4),
                is_suspicious=bool(probability >= threshold or label["is_fake"]),
                flags=label["flags"],
            )
        )

    total = len(analyzed_reviews)
    suspicious = sum(item.is_suspicious for item in analyzed_reviews)
    probabilities_out = [item.fake_probability for item in analyzed_reviews]

    return AnalyzeTikiResponse(
        product_id=product_id,
        product_url=product_url,
        total_reviews=total,
        suspicious_reviews=suspicious,
        fake_rate=round(suspicious / total, 4) if total else 0.0,
        average_fake_probability=round(mean(probabilities_out), 4) if probabilities_out else 0.0,
        model_version=model_version,
        crawl_status=crawl_status,
        crawl_message=crawl_message,
        reviews=analyzed_reviews,
    )


def _demo_reviews(product_id: str) -> list[dict]:
    return [
        {
            "review_id": f"{product_id}-demo-1",
            "product_id": product_id,
            "user_id": "demo-user-1",
            "rating": 5,
            "content": "Sản phẩm tốt, giao hàng nhanh",
            "helpful_count": 0,
            "purchased": False,
            "total_reviews": 1,
        },
        {
            "review_id": f"{product_id}-demo-2",
            "product_id": product_id,
            "user_id": "demo-user-2",
            "rating": 4,
            "content": "Máy dùng ổn sau một tuần, đóng gói chắc chắn, pin đúng như mô tả.",
            "helpful_count": 3,
            "purchased": True,
            "total_reviews": 12,
        },
    ]
