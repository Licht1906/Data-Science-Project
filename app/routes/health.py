from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/health", summary="Health check")
def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }