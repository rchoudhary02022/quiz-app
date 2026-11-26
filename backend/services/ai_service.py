import asyncio
import re

from google import genai
from google.genai import errors, types
from httpx import RequestError, TimeoutException
from pydantic import BaseModel, Field, ValidationError

from backend.config import GEMINI_API_KEY, GEMINI_MODEL, MAX_SOURCE_CHARS
from backend.schemas import GenerateQuizRequest
from backend.services.prompt_engine import build_quiz_prompt


class AIQuestion(BaseModel):
    question: str = Field(min_length=1, description="The question text")
    options: list[str] = Field(description="Ordered answer choices; MCQ option positions correspond to A, B, C, D")
    correct_index: int = Field(ge=0, description="Zero-based index of the correct option")
    explanation: str = Field(min_length=1, description="Meaningful explanation of why the correct option is right")


class QuizAIResponse(BaseModel):
    title: str = Field(min_length=1, description="Short quiz title")
    questions: list[AIQuestion]


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


class QuizContentValidationError(ValueError):
    pass


def _clean_quiz_questions(data: QuizAIResponse, settings: GenerateQuizRequest) -> list[AIQuestion]:
    expected_options = 2 if settings.question_type.value == "True or False" else 4
    cleaned: list[AIQuestion] = []
    seen_questions: set[str] = set()

    for index, item in enumerate(data.questions, start=1):
        question = " ".join(item.question.split())
        options = [" ".join(option.split()) for option in item.options]
        label = f"Question {index}"
        if not question:
            raise QuizContentValidationError(f"{label} has empty question text.")
        if len(options) != expected_options or any(not option for option in options):
            raise QuizContentValidationError(f"{label} must have exactly {expected_options} non-empty options.")
        if len({option.casefold() for option in options}) != expected_options:
            raise QuizContentValidationError(f"{label} contains duplicate options.")
        if item.correct_index >= len(options):
            raise QuizContentValidationError(f"{label} has a correct answer outside its options.")

        explanation = " ".join(item.explanation.split())
        if len(explanation) < 40:
            raise QuizContentValidationError(f"{label} explanation is too short to teach the concept.")
        if re.search(r"\b(because (this|it) is (the )?correct|because that is the answer)\b", explanation, re.I):
            raise QuizContentValidationError(f"{label} explanation is a placeholder instead of reasoning.")
        sentence_count = len([part for part in re.split(r"(?<=[.!?।])(?:\s+|$)", explanation) if part.strip()])
        if sentence_count < 2 or sentence_count > 6:
            raise QuizContentValidationError(f"{label} explanation must contain 2–5 meaningful sentences.")

        normalized = question.casefold()
        if normalized in seen_questions:
            raise QuizContentValidationError(f"{label} duplicates another question.")
        seen_questions.add(normalized)
        cleaned.append(AIQuestion(
            question=question,
            options=options,
            correct_index=item.correct_index,
            explanation=explanation,
        ))

    if len(cleaned) != settings.question_count:
        raise QuizContentValidationError(
            f"Expected {settings.question_count} questions but received {len(cleaned)}."
        )
    return cleaned


def _validation_summary(error: ValidationError) -> str:
    issues = error.errors(include_input=False)
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or 'response'}: {issue['msg']}"
        for issue in issues[:3]
    ) or "response did not match the required schema"


def _parse_ai_response(output_text: str) -> QuizAIResponse:
    candidate = output_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.I | re.S)
    if fenced:
        candidate = fenced.group(1).strip()
    return QuizAIResponse.model_validate_json(candidate)


def _generate_sync(source_text: str, settings: GenerateQuizRequest, source_type: str) -> QuizAIResponse:
    if not GEMINI_API_KEY:
        raise AIConfigurationError("Gemini API key is missing. Add GEMINI_API_KEY to the project's .env file.")

    client = None
    try:
        client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=1.0,
                    max_delay=2.0,
                    exp_base=2.0,
                    jitter=0.3,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )
        base_prompt = build_quiz_prompt(source_text, settings, source_type)
        correction = ""
        last_issue = "Gemini returned an empty response."
        for attempt in range(2):
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=base_prompt + correction,
                config=types.GenerateContentConfig(
                    temperature=0.35,
                    max_output_tokens=min(32_768, 1_024 + settings.question_count * 700),
                    response_mime_type="application/json",
                    response_schema=QuizAIResponse,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW,
                    ),
                ),
            )
            if not response.text:
                last_issue = "Gemini returned an empty response."
            else:
                try:
                    data = _parse_ai_response(response.text)
                    data.questions = _clean_quiz_questions(data, settings)
                    return data
                except ValidationError as exc:
                    last_issue = _validation_summary(exc)
                except QuizContentValidationError as exc:
                    last_issue = str(exc)

            if attempt == 0:
                correction = (
                    "\n\nCORRECTION RETRY: Your previous JSON response was rejected because: "
                    f"{last_issue} Regenerate the entire response, repair this issue, and return only "
                    "complete JSON matching the schema. Do not omit or guess any answer or explanation."
                )
        raise AIProviderError(
            f"Gemini returned an invalid quiz after one correction retry: {last_issue}"
        )
    except AIProviderError:
        raise
    except ValidationError as exc:
        raise AIProviderError("The AI response did not match the required quiz structure. Please try again.") from exc
    except errors.APIError as exc:
        status = getattr(exc, "code", None)
        if status in (401, 403):
            raise AIConfigurationError("Gemini rejected the configured API key. Check GEMINI_API_KEY in .env.") from exc
        if status == 404:
            raise AIConfigurationError(
                f"The configured Gemini model '{GEMINI_MODEL}' is unavailable to this API. "
                "Check GEMINI_MODEL against the models available to your Google AI Studio key."
            ) from exc
        if status == 429:
            raise AIProviderError("Gemini quota or rate limit reached. Wait and check your Google AI Studio usage limits.") from exc
        if status in (408, 500, 502, 503, 504):
            raise AIProviderError(
                "Gemini is temporarily slow or overloaded. The request was retried once; wait briefly and try again."
            ) from exc
        raise AIProviderError(f"Gemini API request failed (status {status or 'unknown'}). Please try again later.") from exc
    except TimeoutException as exc:
        raise AIProviderError(
            "Gemini did not respond within the request limit after one retry. Wait briefly and try again."
        ) from exc
    except RequestError as exc:
        raise AIProviderError("Could not connect to Gemini. Check your internet connection and try again.") from exc
    except Exception as exc:
        # Keep provider internals and request data out of user-visible errors.
        raise AIProviderError("Quiz generation failed. Please retry with a shorter topic or document.") from exc
    finally:
        if client is not None:
            client.close()

async def generate_quiz(source_text: str, settings: GenerateQuizRequest, source_type: str) -> QuizAIResponse:
    if source_type != "notes" or len(source_text) <= MAX_SOURCE_CHARS:
        return await asyncio.to_thread(_generate_sync, source_text, settings, source_type)

    chunks = split_source_text(source_text, MAX_SOURCE_CHARS)
    if len(chunks) > settings.question_count:
        raise AIProviderError(
            f"These notes span {len(chunks)} source sections, but only {settings.question_count} questions were requested. "
            f"Increase the question count to at least {len(chunks)} (maximum 20), or shorten the notes."
        )

    allocations = allocate_questions([len(chunk) for chunk in chunks], settings.question_count)
    results = []
    for chunk, count in zip(chunks, allocations):
        chunk_settings = settings.model_copy(update={"question_count": count})
        result = await asyncio.to_thread(_generate_sync, chunk, chunk_settings, source_type)
        results.extend(result.questions)

    unique_questions = []
    seen = set()
    for question in results:
        normalized = " ".join(question.question.casefold().split())
        if normalized not in seen:
            unique_questions.append(question)
            seen.add(normalized)
    if len(unique_questions) != settings.question_count:
        raise AIProviderError(
            "The note sections produced duplicate questions, so the requested count could not be met. "
            "Try more detailed notes or fewer questions."
        )
    return QuizAIResponse(title="Study Notes Quiz", questions=unique_questions)


def split_source_text(text: str, max_chars: int) -> list[str]:
    """Split notes at paragraph/sentence boundaries while preserving every character."""
    if max_chars < 1:
        raise ValueError("MAX_SOURCE_CHARS must be a positive integer.")
    paragraphs = text.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""

    def append_piece(piece: str) -> None:
        nonlocal current
        if len(current) + len(piece) <= max_chars:
            current += piece
            return
        if current:
            chunks.append(current)
            current = ""
        if len(piece) <= max_chars:
            current = piece
            return
        # Prefer sentence boundaries; retain separators so the full source is preserved.
        sentences = re.split(r"(?<=[.!?])(?=\s)", piece)
        for sentence in sentences:
            while len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                current, sentence = sentence[:max_chars], sentence[max_chars:]
                chunks.append(current)
                current = ""
            if len(current) + len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                current = sentence
            else:
                current += sentence

    for paragraph in paragraphs:
        append_piece(paragraph)
    if current:
        chunks.append(current)
    return chunks or [text]


def allocate_questions(chunk_lengths: list[int], total_questions: int) -> list[int]:
    """Give every chunk one question, then distribute remaining questions by size."""
    if not chunk_lengths or len(chunk_lengths) > total_questions:
        raise ValueError("Each source chunk needs at least one question.")
    remaining = total_questions - len(chunk_lengths)
    total_chars = sum(chunk_lengths) or len(chunk_lengths)
    exact_shares = [remaining * (length / total_chars) for length in chunk_lengths]
    allocations = [1 + int(share) for share in exact_shares]
    leftovers = total_questions - sum(allocations)
    ranking = sorted(range(len(chunk_lengths)), key=lambda i: exact_shares[i] - int(exact_shares[i]), reverse=True)
    for index in ranking[:leftovers]:
        allocations[index] += 1
    return allocations
