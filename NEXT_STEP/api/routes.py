from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.deps import get_model_bundle, get_review_crawler
from api.schemas import AnalyzeTikiRequest, AnalyzeTikiResponse, HealthResponse
from api.services import analyze_tiki_product
from crawlers.review_crawler import ReviewCrawler

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version="0.1.0", timestamp=datetime.now(timezone.utc))


@router.post(
    "/analyze/tiki",
    response_model=AnalyzeTikiResponse,
    summary="Phân tích review nghi ngờ theo URL sản phẩm Tiki",
)
def analyze_tiki(
    request: AnalyzeTikiRequest,
    crawler: ReviewCrawler = Depends(get_review_crawler),
    model_bundle=Depends(get_model_bundle),
) -> AnalyzeTikiResponse:
    return analyze_tiki_product(request, crawler=crawler, model_bundle=model_bundle)
