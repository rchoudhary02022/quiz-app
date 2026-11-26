# Quizora — AI Quiz Generator

Quizora turns a topic or study notes into an interactive quiz. The existing editorial black-and-white design and particle silhouette are retained. The app uses vanilla HTML/CSS/JavaScript, FastAPI, the official Google GenAI Python SDK, Pydantic, and SQLite.

## Features

- Generate 1–20 multiple choice or true/false questions from a topic or uploaded PDF, DOCX, or TXT notes.
- Choose Easy, Medium, or Hard and English, Hindi, or Hinglish.
- Use an auditable prompt template with role, context, few-shot, difficulty, grounding, constraints, and structured output instructions.
- Answer one question at a time, navigate questions, submit answers for server-side scoring, and review explanations.
- Reopen quizzes and review attempt history and best scores.
- Keep correct answers in the backend until submission.

## Requirements

- Python 3.11 or newer (3.12 recommended)
- A Google AI Studio Gemini API key
- VS Code Live Server (or another static file server) for the frontend

## Setup on Windows PowerShell

Run from the project root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The repository includes a local `.env`. Keep it private and do not commit or share it. For a fresh installation, copy `.env.example` to `.env` and set the values:

```powershell
Copy-Item .env.example .env
```

Set `GEMINI_API_KEY` to your key. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`, which was live-verified with structured quiz output. The application uses this configured model and never silently switches to a different one. Other settings:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./database/quizora.db` | SQLAlchemy database URL |
| `MAX_UPLOAD_MB` | `10` | Maximum upload size |
| `MAX_SOURCE_CHARS` | `40000` | Maximum characters per notes chunk; long notes are split at paragraph and sentence boundaries |
| `FRONTEND_ORIGINS` | localhost Live Server ports | Comma-separated allowed browser origins |

## Run the app

In one terminal, from the project root:

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` to use the frontend served by FastAPI on the same origin. You can also open `frontend/index.html` with VS Code Live Server; the configured default origins include ports 5500 and 5501. The API is available at:

- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/docs`

The health endpoint reports whether a key is configured and which model ID is selected; it does not reveal credentials. A configured key does not guarantee quota or model access, so generation errors are reported by the API.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend and AI configuration status |
| POST | `/api/quizzes/generate` | Generate a quiz from a topic |
| POST | `/api/quizzes/generate-from-file` | Generate from PDF, DOCX, or TXT notes |
| GET | `/api/quizzes/{quiz_id}` | Retrieve a quiz without correct answers |
| POST | `/api/quizzes/{quiz_id}/submit` | Evaluate one answer per question and return review |
| GET | `/api/quizzes/history/list` | List recent quizzes, attempts, and best scores |

## Tests

Run the backend API tests with the project virtual environment:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests stub the Gemini call so the API and database behavior is repeatable offline. A separate live generation check requires valid credentials, network access, and available Gemini quota.

## Document and data notes

- Text PDFs, DOCX, and UTF-8 TXT files are processed in memory; uploaded files are not saved. Image-only scanned PDFs need OCR and return an OCR-required message.
- Long documents are split at paragraph and sentence boundaries. Questions are allocated across all chunks; if there are more chunks than requested questions, the API asks for a higher question count or shorter notes rather than omitting sections silently.
- SQLite files and uploads are ignored by Git. Quiz attempts are local to this installation; user accounts are not implemented.
- `GEMINI_API_KEY` stays on the backend and is never sent to browser JavaScript.
