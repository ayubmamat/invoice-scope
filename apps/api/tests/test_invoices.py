import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

pytest.importorskip("multipart")

from app.models import Base, InvoiceSource
from main import get_invoice, list_invoices, upload_invoice


@pytest.fixture
def db_session(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def build_upload_file(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content), headers=Headers({"content-type": content_type}))


def test_upload_invoice_and_list(db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))
    result = asyncio.run(
        upload_invoice(
            file=build_upload_file("invoice.pdf", b"%PDF-1.4 test", "application/pdf"),
            source=InvoiceSource.UPLOAD,
            vendor="Acme",
            db=db_session,
        )
    )

    assert result["vendor"] == "Acme"
    assert result["source"] == "upload"
    assert result["file_path"].endswith(".pdf")
    assert Path(result["file_path"]).exists()

    invoices = list_invoices(db_session)
    assert len(invoices) == 1

    invoice = get_invoice(result["id"], db_session)
    assert invoice["id"] == result["id"]


def test_upload_dedup_returns_409(db_session: Session, tmp_path: Path, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))
    payload = b"%PDF-1.4 duplicate"

    first = asyncio.run(
        upload_invoice(
            file=build_upload_file("duplicate.pdf", payload, "application/pdf"),
            source=InvoiceSource.UPLOAD,
            vendor=None,
            db=db_session,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            upload_invoice(
                file=build_upload_file("duplicate.pdf", payload, "application/pdf"),
                source=InvoiceSource.UPLOAD,
                vendor=None,
                db=db_session,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["invoice_id"] == first["id"]
