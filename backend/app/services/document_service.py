import io
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import Document

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(text.strip())
        return "\n\n".join(pages_text)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise ValueError(f"Could not read PDF file: {str(e)}")


def extract_text_from_txt(file_bytes: bytes) -> str:
    """Extract plain text from TXT/CSV/MD files."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return file_bytes.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace").strip()


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extract text from file bytes according to filename extension."""
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in ("txt", "csv", "md", "json"):
        return extract_text_from_txt(file_bytes)
    else:
        raise ValueError(f"Unsupported file format: .{ext}. Supported formats: PDF, TXT, CSV, MD")


def get_active_knowledge_context(db: Session, account_id: str, max_chars: int = 6000) -> Optional[str]:
    """
    Fetch all active knowledge documents for an account and format
    them into a concise context block for Gemini system prompt.
    """
    documents = (
        db.query(Document)
        .filter(
            Document.whatsapp_account_id == account_id,
            Document.is_active == True
        )
        .order_by(Document.created_at.desc())
        .all()
    )

    if not documents:
        return None

    context_parts = []
    current_length = 0

    for doc in documents:
        header = f"### [Document: {doc.filename}]\n"
        content = doc.extracted_text.strip()
        remaining_space = max_chars - current_length - len(header)
        if remaining_space <= 100:
            break

        if len(content) > remaining_space:
            content = content[:remaining_space] + "… (truncated)"

        context_parts.append(header + content)
        current_length += len(header) + len(content)

    if not context_parts:
        return None

    return "\n\n".join(context_parts)
