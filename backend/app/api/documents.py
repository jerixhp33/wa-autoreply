import os
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import Document, WhatsAppAccount, User
from app.schemas.schemas import DocumentResponse, DocumentDetailResponse
from app.services.auth_service import get_current_user
from app.services.document_service import extract_text_from_file
from app.config import settings

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    account_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verify account ownership
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")

    filename = file.filename or "document.txt"
    ext = filename.lower().split(".")[-1]
    if ext not in ("pdf", "txt", "csv", "md", "json"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type .{ext}. Allowed: PDF, TXT, CSV, MD, JSON"
        )

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Extract text from document
    try:
        extracted = extract_text_from_file(file_bytes, filename)
    except Exception as e:
        logger.error(f"Failed to extract document text: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    if not extracted or not extracted.strip():
        raise HTTPException(status_code=400, detail="No readable text could be extracted from this document")

    # Save to database
    doc = Document(
        whatsapp_account_id=account_id,
        filename=filename,
        file_type=ext,
        file_size=len(file_bytes),
        extracted_text=extracted.strip(),
        is_active=True,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info(f"Uploaded and indexed knowledge document: {filename} ({len(extracted)} chars) for account {account_id}")

    preview = (extracted[:200] + "…") if len(extracted) > 200 else extracted
    return DocumentResponse(
        id=doc.id,
        whatsapp_account_id=doc.whatsapp_account_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        is_active=doc.is_active,
        created_at=doc.created_at,
        extracted_text_preview=preview,
    )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    account_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")

    docs = (
        db.query(Document)
        .filter(Document.whatsapp_account_id == account_id)
        .order_by(Document.created_at.desc())
        .all()
    )

    result = []
    for d in docs:
        preview = (d.extracted_text[:200] + "…") if len(d.extracted_text) > 200 else d.extracted_text
        result.append(DocumentResponse(
            id=d.id,
            whatsapp_account_id=d.whatsapp_account_id,
            filename=d.filename,
            file_type=d.file_type,
            file_size=d.file_size,
            is_active=d.is_active,
            created_at=d.created_at,
            extracted_text_preview=preview,
        ))
    return result


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == doc.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    return DocumentDetailResponse.model_validate(doc)


@router.patch("/{document_id}/toggle", response_model=DocumentResponse)
async def toggle_document_active(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == doc.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    doc.is_active = not doc.is_active
    db.commit()
    db.refresh(doc)

    preview = (doc.extracted_text[:200] + "…") if len(doc.extracted_text) > 200 else doc.extracted_text
    return DocumentResponse(
        id=doc.id,
        whatsapp_account_id=doc.whatsapp_account_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        is_active=doc.is_active,
        created_at=doc.created_at,
        extracted_text_preview=preview,
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == doc.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(doc)
    db.commit()
    return {"message": "Document deleted successfully"}
