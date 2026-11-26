from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class Difficulty(str, Enum):
    easy = "Easy"
    medium = "Medium"
    hard = "Hard"


class QuestionType(str, Enum):
    mcq = "Multiple choice (MCQ)"
    true_false = "True or False"


class GenerateQuizRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    question_count: int = Field(default=10, ge=1, le=20)
    difficulty: Difficulty = Difficulty.medium
    language: str = Field(default="English", pattern="^(English|Hindi|Hinglish)$")
    question_type: QuestionType = QuestionType.mcq


class AnswerSubmission(BaseModel):
    question_id: str
    selected_index: int = Field(ge=0, le=3)


class SubmitQuizRequest(BaseModel):
    answers: list[AnswerSubmission]


class QuestionForQuiz(BaseModel):
    id: str
    question: str
    options: list[str]


class GeneratedQuizResponse(BaseModel):
    quiz_id: str
    title: str
    source_type: str
    question_count: int
    difficulty: str
    language: str
    questions: list[QuestionForQuiz]


class QuestionReview(BaseModel):
    question_id: str
    question: str
    options: list[str]
    selected_index: int | None
    correct_index: int
    is_correct: bool
    explanation: str


class QuizResultResponse(BaseModel):
    quiz_id: str
    score: int
    total: int
    percentage: float
    feedback: str
    reviews: list[QuestionReview]


class HealthResponse(BaseModel):
    status: str
    ai_configured: bool
    model: str
    max_upload_mb: int
