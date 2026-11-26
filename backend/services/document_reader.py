from io import BytesIO
from pathlib import Path

import pymupdf
from docx import Document



class DocumentReadError(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    try:
        if extension == ".pdf":
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                text = "\n".join(page.get_text("text") for page in pdf)
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
        raise DocumentReadError("Very little readable text was found. This may be a scanned PDF; OCR support is not included yet.")
    return text
