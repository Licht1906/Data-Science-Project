from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    timestamp: datetime


class AnalyzeTikiRequest(BaseModel):
    product_url: HttpUrl = Field(..., examples=["https://tiki.vn/san-pham-demo-p123456.html"])
    max_pages: int = Field(2, ge=1, le=20)
    use_live_crawl: bool = Field(True, description="Nếu false, API chỉ trả mock/demo khi chưa có DB.")


class ReviewAnalysis(BaseModel):
    review_id: str
    user_id: str | None = None
    rating: int | None = None
    content: str
    content_clean: str
    fake_probability: float
    is_suspicious: bool
    flags: list[str]


class AnalyzeTikiResponse(BaseModel):
    product_id: str
    product_url: str
    total_reviews: int
    suspicious_reviews: int
    fake_rate: float
    average_fake_probability: float
    model_version: str
    crawl_status: str = "ok"
    crawl_message: str | None = None
    reviews: list[ReviewAnalysis]
