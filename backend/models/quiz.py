from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class QuizRecord(Base):
    __tablename__ = "quizzes"

    id = Column(String(36), primary_key=True, index=True)
    title = Column(String(250), nullable=False)
    topic = Column(String(500), nullable=False, default="")
    source_type = Column(String(20), nullable=False)
    difficulty = Column(String(20), nullable=False)
    language = Column(String(30), nullable=False)
    question_type = Column(String(40), nullable=False)
    question_count = Column(Integer, nullable=False)
    questions_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    attempts = relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(String(36), ForeignKey("quizzes.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    percentage = Column(Float, nullable=False)
    answers_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    quiz = relationship("QuizRecord", back_populates="attempts")
