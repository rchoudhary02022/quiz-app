from pathlib import Path
import os
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'database' / 'quizora.db').as_posix()}")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
MAX_SOURCE_CHARS = int(os.getenv("MAX_SOURCE_CHARS", "40000"))
FRONTEND_ORIGINS = [
    item.strip()
    for item in os.getenv(
        "FRONTEND_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5501,http://localhost:5501",
    ).split(",")
    if item.strip()
]

(ROOT_DIR / "database").mkdir(parents=True, exist_ok=True)
(ROOT_DIR / "uploads").mkdir(parents=True, exist_ok=True)
