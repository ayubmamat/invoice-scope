from collections.abc import Generator
from hashlib import sha256
import os
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Invoice, InvoiceSource
from app.parsing import extract_pdf_text, parse_invoice_text

app = FastAPI(title="InvoiceScope API")


PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_storage_dir() -> Path:
    return Path(os.getenv("INVOICE_STORAGE_DIR", "/data/invoices"))


def invoice_to_dict(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "vendor": invoice.vendor,
        "vendor_domain": invoice.vendor_domain,
        "invoice_number": invoice.invoice_number,
        "billing_period_start": invoice.billing_period_start,
        "billing_period_end": invoice.billing_period_end,
        "invoice_date": invoice.invoice_date,
        "currency": invoice.currency,
        "total_amount": float(invoice.total_amount) if invoice.total_amount is not None else None,
        "tax_amount": float(invoice.tax_amount) if invoice.tax_amount is not None else None,
        "source": invoice.source.value,
        "file_path": invoice.file_path,
        "file_hash": invoice.file_hash,
        "created_at": invoice.created_at,
    }


def is_pdf_upload(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    return file.content_type in PDF_CONTENT_TYPES or filename.endswith(".pdf")


def normalize_invoice_source(source: str) -> InvoiceSource:
    normalized_source = source.strip().lower()
    try:
        return InvoiceSource(normalized_source)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid source '{source}'. Allowed values: upload, email.",
        ) from exc


@app.get("/health")
def health_check(_: Session = Depends(get_db)) -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoices/upload", status_code=status.HTTP_201_CREATED)
async def upload_invoice(
    file: UploadFile = File(...),
    source: str = Form(default=InvoiceSource.UPLOAD.value),
    vendor: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    normalized_source = normalize_invoice_source(source)

    if not is_pdf_upload(file):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    content = await file.read()
    file_hash = sha256(content).hexdigest()

    existing_invoice = db.scalar(select(Invoice).where(Invoice.file_hash == file_hash))
    if existing_invoice is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Invoice already exists", "invoice_id": existing_invoice.id},
        )

    storage_dir = get_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{uuid4()}.pdf"
    file_path.write_bytes(content)

    extracted_text = extract_pdf_text(file_path)
    parsed = parse_invoice_text(extracted_text, filename=file.filename)
    resolved_vendor = (vendor or "").strip() or parsed.vendor or "unknown"

    invoice = Invoice(
        vendor=resolved_vendor,
        invoice_number=parsed.invoice_number,
        billing_period_start=parsed.billing_period_start,
        billing_period_end=parsed.billing_period_end,
        invoice_date=parsed.invoice_date,
        currency=parsed.currency,
        total_amount=parsed.total_amount,
        tax_amount=parsed.tax_amount,
        source=normalized_source,
        file_path=str(file_path),
        file_hash=file_hash,
        extracted_text=extracted_text or None,
    )

    db.add(invoice)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_invoice = db.scalar(select(Invoice).where(Invoice.file_hash == file_hash))
        if existing_invoice is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Invoice already exists", "invoice_id": existing_invoice.id},
            )
        raise

    db.refresh(invoice)
    return invoice_to_dict(invoice)


@app.get("/invoices")
def list_invoices(db: Session = Depends(get_db)) -> list[dict]:
    invoices = db.scalars(select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(50)).all()
    return [invoice_to_dict(invoice) for invoice in invoices]


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)) -> dict:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice_to_dict(invoice)


@app.get("/invoices/{invoice_id}/text")
def get_invoice_text(invoice_id: int, db: Session = Depends(get_db)) -> dict[str, int | str]:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    return {"id": invoice.id, "text": (invoice.extracted_text or "")[:5000]}
