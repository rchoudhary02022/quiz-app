from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.config import FRONTEND_ORIGINS, GEMINI_API_KEY, GEMINI_MODEL, MAX_UPLOAD_BYTES
from backend.database import Base, engine
from backend.models import quiz  # noqa: F401 - registers SQLAlchemy models
from backend.routes.quizzes import router as quizzes_router
from backend.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Quizora AI Quiz Generator API",
    description="Prompt-engineered quiz generation from topics and uploaded study notes.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(quizzes_router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health():
    return HealthResponse(
        status="ok",
        ai_configured=bool(GEMINI_API_KEY),
        model=GEMINI_MODEL,
        max_upload_mb=max(1, MAX_UPLOAD_BYTES // (1024 * 1024)),
    )


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
