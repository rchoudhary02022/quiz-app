from io import BytesIO
from pathlib import Path

import pymupdf
from docx import Document
from google import genai
from google.genai import errors, types

from backend.config import GEMINI_API_KEY, GEMINI_MODEL



class DocumentReadError(ValueError):
    pass


def _ocr_pdf(content: bytes) -> str:
    """Read scanned PDF pages with the same Gemini configuration used for quiz generation."""
    if not GEMINI_API_KEY:
        raise DocumentReadError(
            "This PDF appears to be scanned. Add GEMINI_API_KEY to the project's .env file to read scanned PDFs."
        )

    client = None
    try:
        client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=90_000,
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
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                "Transcribe all readable text in this PDF faithfully and in reading order. "
                "Preserve headings, lists, equations, and page breaks where practical. "
                "Return only the transcription. Do not summarize, infer, or add facts.",
                types.Part.from_bytes(data=content, mime_type="application/pdf"),
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=16_000,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        return (response.text or "").strip()
    except DocumentReadError:
        raise
    except errors.APIError as exc:
        status = getattr(exc, "code", None)
        if status in (401, 403):
            message = "Gemini rejected the configured API key. Check GEMINI_API_KEY in .env."
        elif status == 404:
            message = f"The configured Gemini model '{GEMINI_MODEL}' cannot read this PDF. Check GEMINI_MODEL in .env."
        elif status == 429:
            message = "Gemini quota or rate limit reached while reading the scanned PDF. Wait and try again."
        elif status in (408, 500, 502, 503, 504):
            message = "Gemini timed out while reading the scanned PDF. Wait briefly and try again."
        else:
            message = "Gemini could not read the scanned PDF. Check the file and try again."
        raise DocumentReadError(message) from exc
    except Exception as exc:
        raise DocumentReadError(
            "Could not read the scanned PDF with Gemini. Check your internet connection and try again."
        ) from exc
    finally:
        if client is not None:
            client.close()


def extract_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    try:
        if extension == ".pdf":
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                text = "\n".join(page.get_text("text") for page in pdf)
            if len("".join(text.split())) < 40:
                text = _ocr_pdf(content)
        elif extension == ".docx":
            document = Document(BytesIO(content))
            chunks = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    chunks.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(chunks)
        elif extension == ".txt":
            text = content.decode("utf-8-sig")
        else:
            raise DocumentReadError("Unsupported file type. Upload PDF, DOCX or TXT. Legacy .doc files are not supported.")
    except DocumentReadError:
        raise
    except Exception as exc:
        raise DocumentReadError("Could not read this file. Check that it is a valid, non-password-protected document.") from exc

    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) < 40:
        raise DocumentReadError("Very little readable text was found in this file. Try a clearer or text-based document.")
    return text
