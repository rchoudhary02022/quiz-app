import json
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import MAX_UPLOAD_BYTES
from backend.database import get_db
from backend.models.quiz import QuizRecord, QuizAttempt
from backend.schemas import (
    AnswerSubmission, Difficulty, GenerateQuizRequest, GeneratedQuizResponse,
    QuestionForQuiz, QuestionReview, QuizResultResponse, QuestionType,
    SubmitQuizRequest,
)
from backend.services.ai_service import generate_quiz, AIConfigurationError, AIProviderError
from backend.services.document_reader import extract_text, DocumentReadError

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


def _save_quiz(db: Session, ai_result, settings: GenerateQuizRequest, source_type: str) -> GeneratedQuizResponse:
    quiz_id = str(uuid4())
    stored_questions = []
    public_questions = []
    for index, question in enumerate(ai_result.questions, start=1):
        question_id = f"q{index}"
        stored_questions.append({
            "id": question_id,
            "question": question.question,
            "options": question.options,
            "correct_index": question.correct_index,
            "explanation": question.explanation,
        })
        public_questions.append(QuestionForQuiz(
            id=question_id,
            question=question.question,
            options=question.options,
        ))

    record = QuizRecord(
        id=quiz_id,
        title=ai_result.title[:250],
        topic=settings.topic[:500],
        source_type=source_type,
        difficulty=settings.difficulty.value,
        language=settings.language,
        question_type=settings.question_type.value,
        question_count=len(stored_questions),
        questions_json=json.dumps(stored_questions, ensure_ascii=False),
    )
    db.add(record)
    db.commit()
    return GeneratedQuizResponse(
        quiz_id=quiz_id,
        title=record.title,
        source_type=source_type,
        question_count=record.question_count,
        difficulty=record.difficulty,
        language=record.language,
        questions=public_questions,
    )


async def _run_generation(source_text: str, settings: GenerateQuizRequest, source_type: str, db: Session):
    try:
        result = await generate_quiz(source_text, settings, source_type)
        return _save_quiz(db, result, settings, source_type)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/generate", response_model=GeneratedQuizResponse)
async def generate_from_topic(payload: GenerateQuizRequest, db: Session = Depends(get_db)):
    return await _run_generation(payload.topic.strip(), payload, "topic", db)


@router.post("/generate-from-file", response_model=GeneratedQuizResponse)
async def generate_from_file(
    file: UploadFile = File(...),
    question_count: int = Form(10),
    difficulty: Difficulty = Form(Difficulty.medium),
    language: str = Form("English"),
    question_type: QuestionType = Form(QuestionType.mcq),
    db: Session = Depends(get_db),
):
    supplied_filename = file.filename or "uploaded-file"
    filename = Path(supplied_filename.replace("\\", "/")).name
    filename = "".join(character for character in filename if character.isprintable())[:180] or "uploaded-file"
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=415, detail="Upload PDF, DOCX or TXT. Legacy .doc files are not supported.")
    expected_types = {
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"},
        ".txt": {"text/plain", "application/octet-stream"},
    }
    content_type = (file.content_type or "application/octet-stream").split(";")[0].lower()
    if content_type not in expected_types[extension]:
        raise HTTPException(status_code=415, detail="The uploaded file type does not match its filename extension.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = max(1, MAX_UPLOAD_BYTES // (1024 * 1024))
        raise HTTPException(status_code=413, detail=f"File exceeds the {limit_mb} MB upload limit.")
    try:
        extracted = extract_text(filename, content)
    except DocumentReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        settings = GenerateQuizRequest(
            topic=f"Questions based on uploaded document: {filename}",
            question_count=question_count,
            difficulty=difficulty,
            language=language,
            question_type=question_type,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid quiz settings.") from exc
    return await _run_generation(extracted, settings, "notes", db)


@router.get("/{quiz_id}", response_model=GeneratedQuizResponse)
def get_quiz(quiz_id: str, db: Session = Depends(get_db)):
    record = db.get(QuizRecord, quiz_id)
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    questions = json.loads(record.questions_json)
    return GeneratedQuizResponse(
        quiz_id=record.id,
        title=record.title,
        source_type=record.source_type,
        question_count=record.question_count,
        difficulty=record.difficulty,
        language=record.language,
        questions=[QuestionForQuiz(id=q["id"], question=q["question"], options=q["options"]) for q in questions],
    )


@router.post("/{quiz_id}/submit", response_model=QuizResultResponse)
def submit_quiz(quiz_id: str, payload: SubmitQuizRequest, db: Session = Depends(get_db)):
    record = db.get(QuizRecord, quiz_id)
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    questions = json.loads(record.questions_json)
    submitted = {answer.question_id: answer.selected_index for answer in payload.answers}
    expected_ids = {question["id"] for question in questions}
    submitted_ids = [answer.question_id for answer in payload.answers]
    if len(submitted_ids) != len(expected_ids) or set(submitted_ids) != expected_ids:
        raise HTTPException(status_code=422, detail="Submit exactly one answer for every quiz question.")
    score = 0
    reviews = []
    for question in questions:
        selected = submitted.get(question["id"])
        if selected >= len(question["options"]):
            raise HTTPException(status_code=422, detail="An answer selection is outside the available options.")
        correct = selected == question["correct_index"]
        score += int(correct)
        reviews.append(QuestionReview(
            question_id=question["id"],
            question=question["question"],
            options=question["options"],
            selected_index=selected,
            correct_index=question["correct_index"],
            is_correct=correct,
            explanation=question["explanation"],
        ))
    total = len(questions)
    percentage = round((score / total) * 100, 1) if total else 0.0
    feedback = "Excellent work — strong understanding." if percentage >= 85 else "Good progress — review the explanations and try again." if percentage >= 60 else "Keep practising — revisit the concepts and take another attempt."
    db.add(QuizAttempt(
        quiz_id=quiz_id,
        score=score,
        total=total,
        percentage=percentage,
        answers_json=json.dumps(submitted),
    ))
    db.commit()
    return QuizResultResponse(
        quiz_id=quiz_id,
        score=score,
        total=total,
        percentage=percentage,
        feedback=feedback,
        reviews=reviews,
    )


@router.get("/history/list")
def quiz_history(limit: int = 20, db: Session = Depends(get_db)):
    records = db.query(QuizRecord).order_by(QuizRecord.created_at.desc()).limit(min(max(limit, 1), 100)).all()
    return [{
        "quiz_id": item.id,
        "title": item.title,
        "topic": item.topic,
        "source_type": item.source_type,
        "difficulty": item.difficulty,
        "question_count": item.question_count,
        "created_at": item.created_at.isoformat(),
        "attempts": len(item.attempts),
        "best_score": max((attempt.percentage for attempt in item.attempts), default=None),
    } for item in records]
