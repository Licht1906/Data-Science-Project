from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.tiki import TikiAnalyzeRequest, TikiAnalyzeResponse, ErrorResponse
from app.deps import get_model, get_review_crawler
from app.services.analyzer import TikiAnalyzerService

router = APIRouter()


@router.post(
    "/tiki",
    response_model=TikiAnalyzeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "URL không hợp lệ hoặc không phải Tiki"},
        404: {"model": ErrorResponse, "description": "Không tìm thấy review"},
        503: {"model": ErrorResponse, "description": "Lỗi crawl hoặc model chưa sẵn sàng"},
    },
    summary="Phân tích review sản phẩm Tiki theo URL",
)
def analyze_tiki(
    request: TikiAnalyzeRequest,
    model=Depends(get_model),
    crawler=Depends(get_review_crawler),
):
    """
    Nhận URL sản phẩm Tiki, trả về:
    - Tổng quan sản phẩm (số review, tỷ lệ fake, mức rủi ro)
    - Danh sách từng review kèm xác suất fake và cờ heuristic
    """
    # Validate URL
    if "tiki.vn" not in request.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL không hợp lệ — chỉ hỗ trợ sản phẩm trên tiki.vn",
        )

    service = TikiAnalyzerService(crawler=crawler, model=model)

    try:
        result = service.analyze(request.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    if result is None or result.product.total_reviews == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy review cho sản phẩm này",
        )

    return result