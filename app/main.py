from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, analyze

app = FastAPI(
    title="Tiki Fake Review Detector API",
    description="API phát hiện review không đáng tin trên Tiki",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cập nhật khi deploy thật
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(analyze.router, prefix="/analyze", tags=["Analyze"])