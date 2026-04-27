from pydantic import BaseModel, HttpUrl, Field
from typing import Optional
from datetime import datetime


# ---------- Request ----------

class TikiAnalyzeRequest(BaseModel):
    url: str = Field(
        ...,
        example="https://tiki.vn/san-pham/abc-xyz-p123456.html",
        description="URL sản phẩm trên Tiki",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://tiki.vn/san-pham/abc-xyz-p123456.html"
            }
        }


# ---------- Response ----------

class ReviewResult(BaseModel):
    review_id: str
    content: str
    rating: int
    fake_probability: float = Field(..., ge=0.0, le=1.0)
    is_fake: bool
    flags: list[str] = Field(default_factory=list, description="Các cờ heuristic kích hoạt")
    reviewer: Optional[str] = None
    created_at: Optional[str] = None


class ProductSummary(BaseModel):
    product_id: str
    product_name: str
    total_reviews: int
    fake_count: int
    fake_ratio: float = Field(..., ge=0.0, le=1.0)
    avg_rating: float
    risk_level: str = Field(..., description="LOW / MEDIUM / HIGH")


class TikiAnalyzeResponse(BaseModel):
    product: ProductSummary
    reviews: list[ReviewResult]
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    model_version: Optional[str] = None


# ---------- Error ----------

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None