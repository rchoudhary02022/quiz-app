import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, engine as app_engine, get_db
from backend.main import app
from backend.routes import quizzes as quiz_routes
from backend.services.ai_service import AIQuestion, QuizAIResponse
from backend.services.ai_service import allocate_questions, split_source_text


class QuizApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=cls.engine)

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=cls.engine)
        cls.engine.dispose()
        app_engine.dispose()

    def setUp(self):
        self.original_generate = quiz_routes.generate_quiz

        async def fake_generate(source_text, settings, source_type):
            questions = [
                AIQuestion(
                    question=f"Question {index + 1} about {source_text[:20]}",
                    options=["A", "B", "C", "D"],
                    correct_index=1,
                    explanation="B is supported by the material.",
                )
                for index in range(settings.question_count)
            ]
            return QuizAIResponse(title="Test quiz", questions=questions)

        quiz_routes.generate_quiz = fake_generate

    def tearDown(self):
        quiz_routes.generate_quiz = self.original_generate
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_generate_retrieve_submit_and_history(self):
        generated = self.client.post("/api/quizzes/generate", json={
            "topic": "Cell biology", "question_count": 2, "difficulty": "Easy",
            "language": "English", "question_type": "Multiple choice (MCQ)",
        })
        self.assertEqual(generated.status_code, 200, generated.text)
        quiz = generated.json()
        self.assertEqual(len(quiz["questions"]), 2)
        self.assertNotIn("correct_index", quiz["questions"][0])

        retrieved = self.client.get(f"/api/quizzes/{quiz['quiz_id']}")
        self.assertEqual(retrieved.status_code, 200)
        self.assertNotIn("correct_index", retrieved.text)

        incomplete = self.client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", json={"answers": []})
        self.assertEqual(incomplete.status_code, 422)
        result = self.client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", json={
            "answers": [
                {"question_id": "q1", "selected_index": 1},
                {"question_id": "q2", "selected_index": 0},
            ],
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["score"], 1)
        self.assertEqual(result.json()["percentage"], 50.0)

        history = self.client.get("/api/quizzes/history/list")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["attempts"], 1)
        self.assertEqual(history.json()[0]["best_score"], 50.0)

    def test_document_formats_and_invalid_extension(self):
        text = b"Photosynthesis converts light energy into chemical energy inside plants. " * 2
        txt = self.client.post("/api/quizzes/generate-from-file", files={"file": ("notes.txt", text, "text/plain")}, data={
            "question_count": "1", "difficulty": "Easy", "language": "English",
            "question_type": "Multiple choice (MCQ)",
        })
        self.assertEqual(txt.status_code, 200, txt.text)

        from docx import Document
        from io import BytesIO
        document = Document()
        document.add_paragraph(text.decode())
        buffer = BytesIO()
        document.save(buffer)
        docx = self.client.post("/api/quizzes/generate-from-file", files={
            "file": ("notes.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }, data={"question_count": "1", "difficulty": "Easy", "language": "English", "question_type": "Multiple choice (MCQ)"})
        self.assertEqual(docx.status_code, 200, docx.text)

        import pymupdf
        pdf_doc = pymupdf.open()
        page = pdf_doc.new_page()
        page.insert_text((50, 50), text.decode()[:100])
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()
        pdf_result = self.client.post("/api/quizzes/generate-from-file", files={
            "file": ("notes.pdf", pdf_bytes, "application/pdf")
        }, data={"question_count": "1", "difficulty": "Easy", "language": "English", "question_type": "Multiple choice (MCQ)"})
        self.assertEqual(pdf_result.status_code, 200, pdf_result.text)

        rejected = self.client.post("/api/quizzes/generate-from-file", files={"file": ("notes.exe", b"bad", "application/octet-stream")})
        self.assertEqual(rejected.status_code, 415)

    def test_invalid_topic_is_rejected(self):
        response = self.client.post("/api/quizzes/generate", json={"topic": "x"})
        self.assertEqual(response.status_code, 422)

    def test_long_notes_are_chunked_without_dropping_text(self):
        source = "Opening paragraph.\n" + ("A longer section explains the concept clearly. " * 8)
        chunks = split_source_text(source, 48)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), source)
        self.assertTrue(all(len(chunk) <= 48 for chunk in chunks))

        allocations = allocate_questions([len(chunk) for chunk in chunks], len(chunks) + 5)
        self.assertEqual(sum(allocations), len(chunks) + 5)
        self.assertTrue(all(count >= 1 for count in allocations))


if __name__ == "__main__":
    unittest.main()
