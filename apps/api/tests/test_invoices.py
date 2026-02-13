import asyncio
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

pytest.importorskip("multipart")

from app.models import Base, Invoice, InvoiceSource
FIXTURES_DIR = Path(__file__).parent / "fixtures"

from main import (
    parse_existing_invoice,
    get_invoice,
    get_invoice_text,
    get_monthly_mom_report,
    get_monthly_report,
    get_anomalies_report,
    get_trend_report,
    previous_year_month,
    seed_dev_data,
    get_vendor_report,
    list_invoices,
    upload_invoice,
)


def build_pdf_with_text(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    stream = DecodedStreamObject()
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 20 120 Td ({escaped_text}) Tj ET".encode("utf-8"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    pdf = BytesIO()
    writer.write(pdf)
    return pdf.getvalue()


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
            source="upload",
            vendor="Acme",
            db=db_session,
        )
    )

    assert result["vendor"] == "Acme"
    assert result["source"] == "upload"
    assert result["file_path"].endswith(".pdf")
    assert Path(result["file_path"]).exists()
    assert result["subtotal_amount"] is None
    assert result["amount_paid"] is None
    assert result["amount_due"] is None
    assert result["status"] is None

    invoices = list_invoices(db_session)
    assert len(invoices) == 1

    invoice = get_invoice(result["id"], db_session)
    assert invoice["id"] == result["id"]




def test_get_invoice_text_returns_extracted_text(db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))
    payload = build_pdf_with_text("InvoiceScope PDF extraction check")
    result = asyncio.run(
        upload_invoice(
            file=build_upload_file("invoice.pdf", payload, "application/pdf"),
            source="upload",
            vendor="Acme",
            db=db_session,
        )
    )

    response = get_invoice_text(result["id"], db_session)
    assert response["id"] == result["id"]
    assert response["text"]
    assert len(response["text"].strip()) > 0

def test_upload_dedup_returns_409(db_session: Session, tmp_path: Path, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))
    payload = b"%PDF-1.4 duplicate"

    first = asyncio.run(
        upload_invoice(
            file=build_upload_file("duplicate.pdf", payload, "application/pdf"),
            source="upload",
            vendor=None,
            db=db_session,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            upload_invoice(
                file=build_upload_file("duplicate.pdf", payload, "application/pdf"),
                source="upload",
                vendor=None,
                db=db_session,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["invoice_id"] == first["id"]


def test_reparse_updates_null_fields(db_session: Session, tmp_path: Path, monkeypatch):
    invoice_pdf = tmp_path / "aws.pdf"
    invoice_pdf.write_bytes(b"%PDF-1.4")

    invoice = Invoice(
        vendor="unknown",
        invoice_number=None,
        billing_period_start=None,
        billing_period_end=None,
        invoice_date=None,
        currency=None,
        total_amount=None,
        tax_amount=None,
        source=InvoiceSource.UPLOAD,
        file_path=str(invoice_pdf),
        file_hash="hash-reparse-null",
        extracted_text=None,
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    aws_text = (FIXTURES_DIR / "aws_tax_invoice_text.txt").read_text()

    def fake_extract_pdf_text(file_path: Path) -> str:
        assert file_path == invoice_pdf
        return aws_text

    monkeypatch.setattr("main.extract_pdf_text", fake_extract_pdf_text)

    response = parse_existing_invoice(invoice.id, db=db_session)

    assert response["vendor"] == "AWS"
    assert response["currency"] == "USD"
    assert response["total_amount"] == 1282.37
    assert response["tax_amount"] == 105.88
    assert response["billing_period_start"] == date(2025, 12, 1)
    assert response["billing_period_end"] == date(2025, 12, 31)


def test_reparse_idempotent(db_session: Session, tmp_path: Path, monkeypatch):
    invoice_pdf = tmp_path / "aws.pdf"
    invoice_pdf.write_bytes(b"%PDF-1.4")
    aws_text = (FIXTURES_DIR / "aws_tax_invoice_text.txt").read_text()

    invoice = Invoice(
        vendor="unknown",
        invoice_number=None,
        billing_period_start=None,
        billing_period_end=None,
        invoice_date=None,
        currency=None,
        total_amount=None,
        tax_amount=None,
        source=InvoiceSource.UPLOAD,
        file_path=str(invoice_pdf),
        file_hash="hash-reparse-idempotent",
        extracted_text=aws_text,
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    def fail_if_called(_: Path) -> str:
        raise AssertionError("extract_pdf_text should not be called when extracted_text is already present")

    monkeypatch.setattr("main.extract_pdf_text", fail_if_called)

    first = parse_existing_invoice(invoice.id, db=db_session)
    second = parse_existing_invoice(invoice.id, db=db_session)

    assert first["vendor"] == "AWS"
    assert second["vendor"] == "AWS"
    assert first["currency"] == second["currency"] == "USD"
    assert first["total_amount"] == second["total_amount"] == 1282.37
    assert first["tax_amount"] == second["tax_amount"] == 105.88




def test_reparse_vendor_specific_azure_and_freshdesk(db_session: Session, tmp_path: Path):
    aws_pdf = tmp_path / "aws.pdf"
    azure_pdf = tmp_path / "azure.pdf"
    freshdesk_pdf = tmp_path / "freshdesk.pdf"
    for pdf in (aws_pdf, azure_pdf, freshdesk_pdf):
        pdf.write_bytes(b"%PDF-1.4")

    aws_invoice = Invoice(
        vendor="unknown",
        source=InvoiceSource.UPLOAD,
        file_path=str(aws_pdf),
        file_hash="hash-aws-seed",
        extracted_text=(FIXTURES_DIR / "aws_tax_invoice_text.txt").read_text(),
    )
    azure_invoice = Invoice(
        vendor="unknown",
        source=InvoiceSource.UPLOAD,
        file_path=str(azure_pdf),
        file_hash="hash-azure-seed",
        extracted_text=(FIXTURES_DIR / "azure_invoice_text.txt").read_text(),
    )
    freshdesk_invoice = Invoice(
        vendor="unknown",
        source=InvoiceSource.UPLOAD,
        file_path=str(freshdesk_pdf),
        file_hash="hash-freshdesk-seed",
        extracted_text=(FIXTURES_DIR / "freshdesk_invoice_text.txt").read_text(),
    )

    db_session.add_all([aws_invoice, azure_invoice, freshdesk_invoice])
    db_session.commit()

    azure_response = parse_existing_invoice(azure_invoice.id, db=db_session)
    freshdesk_response = parse_existing_invoice(freshdesk_invoice.id, db=db_session)

    assert azure_response["vendor"] == "Microsoft Azure"
    assert azure_response["invoice_number"] == "G139702701"
    assert azure_response["invoice_date"] == date(2026, 2, 9)
    assert azure_response["billing_period_start"] == date(2026, 1, 1)
    assert azure_response["billing_period_end"] == date(2026, 1, 31)
    assert azure_response["currency"] == "USD"
    assert azure_response["subtotal_amount"] == 0.5
    assert azure_response["total_amount"] == 0.55
    assert azure_response["tax_amount"] == 0.05
    assert azure_response["amount_due"] is None
    assert azure_response["status"] == "UNKNOWN"

    assert freshdesk_response["vendor"] == "Freshdesk"
    assert freshdesk_response["invoice_number"] == "FD2581504"
    assert freshdesk_response["invoice_date"] == date(2026, 1, 13)
    assert freshdesk_response["billing_period_start"] == date(2026, 1, 13)
    assert freshdesk_response["billing_period_end"] == date(2026, 2, 13)
    assert freshdesk_response["currency"] == "USD"
    assert freshdesk_response["subtotal_amount"] == 234.0
    assert freshdesk_response["total_amount"] == 234.0
    assert freshdesk_response["amount_paid"] == 234.0
    assert freshdesk_response["amount_due"] == 0.0
    assert freshdesk_response["status"] == "PAID"
    assert freshdesk_response["tax_amount"] is None

def test_upload_source_normalized_to_lowercase(db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))
    result = asyncio.run(
        upload_invoice(
            file=build_upload_file("invoice.pdf", b"%PDF-1.4 test", "application/pdf"),
            source="UPLOAD",
            vendor="Acme",
            db=db_session,
        )
    )

    assert result["source"] == "upload"

    stored_invoice = db_session.get(Invoice, result["id"])
    assert stored_invoice is not None
    assert stored_invoice.source == InvoiceSource.UPLOAD


def test_upload_invalid_source_returns_422(db_session: Session, tmp_path: Path, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("INVOICE_STORAGE_DIR", str(tmp_path / "invoices"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            upload_invoice(
                file=build_upload_file("invoice.pdf", b"%PDF-1.4 test", "application/pdf"),
                source="ftp",
                vendor="Acme",
                db=db_session,
            )
        )

    assert exc.value.status_code == 422
    assert "Allowed values: upload, email" in exc.value.detail


def test_monthly_report_overlapping_billing_period_and_invoice_date_fallback(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("100.00"),
                tax_amount=Decimal("10.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-dec.pdf",
                file_hash="hash-aws-dec",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 15),
                billing_period_end=date(2025, 12, 15),
                invoice_date=date(2025, 12, 15),
                currency="USD",
                total_amount=Decimal("40.00"),
                tax_amount=Decimal("4.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-overlap.pdf",
                file_hash="hash-aws-overlap",
            ),
            Invoice(
                vendor="Stripe",
                invoice_date=date(2025, 12, 20),
                currency="EUR",
                total_amount=Decimal("80.00"),
                tax_amount=Decimal("8.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/stripe-dec.pdf",
                file_hash="hash-stripe-dec",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2026, 1, 1),
                billing_period_end=date(2026, 1, 31),
                invoice_date=date(2026, 1, 31),
                currency="USD",
                total_amount=Decimal("999.00"),
                tax_amount=Decimal("99.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-jan.pdf",
                file_hash="hash-aws-jan",
            ),
        ]
    )
    db_session.commit()

    report = get_monthly_report(year=2025, month=12, db=db_session)

    assert report.year == 2025
    assert report.month == 12
    assert [group.model_dump() for group in report.groups] == [
        {
            "vendor": "AWS",
            "currency": "USD",
            "invoice_count": 2,
            "total_amount_sum": 140.0,
            "tax_amount_sum": 14.0,
        },
        {
            "vendor": "Stripe",
            "currency": "EUR",
            "invoice_count": 1,
            "total_amount_sum": 80.0,
            "tax_amount_sum": 8.0,
        },
    ]
    assert [total.model_dump() for total in report.grand_totals] == [
        {
            "currency": "EUR",
            "invoice_count": 1,
            "total_amount_sum": 80.0,
            "tax_amount_sum": 8.0,
        },
        {
            "currency": "USD",
            "invoice_count": 2,
            "total_amount_sum": 140.0,
            "tax_amount_sum": 14.0,
        },
    ]


def test_vendor_report_lifetime_grouped_by_vendor_and_currency(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                invoice_date=date(2025, 12, 1),
                currency="USD",
                total_amount=Decimal("100.00"),
                tax_amount=Decimal("10.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-1.pdf",
                file_hash="hash-vendor-1",
            ),
            Invoice(
                vendor="AWS",
                invoice_date=date(2025, 12, 2),
                currency="USD",
                total_amount=Decimal("50.00"),
                tax_amount=Decimal("5.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-2.pdf",
                file_hash="hash-vendor-2",
            ),
            Invoice(
                vendor="AWS",
                invoice_date=date(2025, 12, 3),
                currency="EUR",
                total_amount=Decimal("70.00"),
                tax_amount=Decimal("7.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-3.pdf",
                file_hash="hash-vendor-3",
            ),
            Invoice(
                vendor="Stripe",
                invoice_date=date(2025, 12, 4),
                currency="USD",
                total_amount=Decimal("20.00"),
                tax_amount=Decimal("2.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/stripe-1.pdf",
                file_hash="hash-vendor-4",
            ),
        ]
    )
    db_session.commit()

    report = get_vendor_report(db_session)

    assert [vendor.model_dump() for vendor in report.vendors] == [
        {"vendor": "AWS", "currency": "EUR", "invoice_count": 1, "total_amount_sum": 70.0},
        {"vendor": "AWS", "currency": "USD", "invoice_count": 2, "total_amount_sum": 150.0},
        {"vendor": "Stripe", "currency": "USD", "invoice_count": 1, "total_amount_sum": 20.0},
    ]


def test_previous_year_month_rollover():
    assert previous_year_month(2026, 1) == (2025, 12)
    assert previous_year_month(2026, 6) == (2026, 5)


def test_monthly_mom_report_pct_change_handles_missing_and_zero_previous(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 1),
                billing_period_end=date(2025, 11, 30),
                invoice_date=date(2025, 11, 30),
                currency="USD",
                total_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-prev-zero.pdf",
                file_hash="hash-aws-prev-zero",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("50.00"),
                tax_amount=Decimal("5.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-current.pdf",
                file_hash="hash-aws-current",
            ),
            Invoice(
                vendor="Cloudflare",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("30.00"),
                tax_amount=Decimal("3.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/cloudflare-current.pdf",
                file_hash="hash-cloudflare-current",
            ),
        ]
    )
    db_session.commit()

    mom_report = get_monthly_mom_report(year=2025, month=12, db=db_session)
    aws_group = next(group for group in mom_report.groups if group.vendor == "AWS" and group.currency == "USD")
    cloudflare_group = next(
        group for group in mom_report.groups if group.vendor == "Cloudflare" and group.currency == "USD"
    )

    assert aws_group.prev_total_amount_sum == 0.0
    assert aws_group.pct_total_amount_change is None
    assert aws_group.prev_tax_amount_sum == 0.0
    assert aws_group.pct_tax_amount_change is None

    assert cloudflare_group.prev_total_amount_sum is None
    assert cloudflare_group.pct_total_amount_change is None


def test_monthly_mom_group_matching_is_vendor_and_currency(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 1),
                billing_period_end=date(2025, 11, 30),
                invoice_date=date(2025, 11, 30),
                currency="EUR",
                total_amount=Decimal("200.00"),
                tax_amount=Decimal("20.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-prev-eur.pdf",
                file_hash="hash-aws-prev-eur",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("300.00"),
                tax_amount=Decimal("30.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-current-usd.pdf",
                file_hash="hash-aws-current-usd",
            ),
        ]
    )
    db_session.commit()

    mom_report = get_monthly_mom_report(year=2025, month=12, db=db_session)
    aws_usd = next(group for group in mom_report.groups if group.vendor == "AWS" and group.currency == "USD")
    aws_eur = next(group for group in mom_report.groups if group.vendor == "AWS" and group.currency == "EUR")

    assert aws_usd.total_amount_sum == 300.0
    assert aws_usd.prev_total_amount_sum is None
    assert aws_usd.pct_total_amount_change is None

    assert aws_eur.total_amount_sum == 0.0
    assert aws_eur.prev_total_amount_sum == 200.0
    assert aws_eur.delta_total_amount == -200.0


def test_monthly_mom_report_december_with_no_previous_returns_null_pct(db_session: Session):
    db_session.add(
        Invoice(
            vendor="AWS",
            billing_period_start=date(2025, 12, 1),
            billing_period_end=date(2025, 12, 31),
            invoice_date=date(2025, 12, 31),
            currency="USD",
            total_amount=Decimal("1282.37"),
            tax_amount=Decimal("105.88"),
            source=InvoiceSource.UPLOAD,
            file_path="/tmp/aws-dec-only.pdf",
            file_hash="hash-aws-dec-only",
        )
    )
    db_session.commit()

    mom_report = get_monthly_mom_report(year=2025, month=12, db=db_session)

    assert mom_report.previous.groups == []
    assert mom_report.previous.grand_totals == []
    assert len(mom_report.groups) == 1
    assert mom_report.groups[0].pct_total_amount_change is None
    assert mom_report.groups[0].pct_tax_amount_change is None


def test_dev_seed_endpoint_enforced_and_seeds_data(db_session: Session, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("ENV", raising=False)
    with pytest.raises(HTTPException) as exc:
        seed_dev_data(db=db_session)
    assert exc.value.status_code == 404

    monkeypatch.setenv("ENV", "dev")
    seeded = seed_dev_data(db=db_session)
    assert seeded["status"] == "ok"

    today = date.today()
    payload = get_monthly_mom_report(year=today.year, month=today.month, db=db_session).model_dump()

    aws_group = next(
        group for group in payload["groups"] if group["vendor"] == "AWS" and group["currency"] == "USD"
    )
    assert aws_group["prev_total_amount_sum"] == 1000.0
    assert aws_group["total_amount_sum"] == 1282.37
    assert aws_group["delta_total_amount"] == 282.37
    assert aws_group["pct_total_amount_change"] == pytest.approx(28.237)

    aws_currency_total = next(total for total in payload["grand_totals"] if total["currency"] == "USD")
    assert aws_currency_total["prev_tax_amount_sum"] == 80.0
    assert aws_currency_total["tax_amount_sum"] == 105.88


def test_trend_report_month_bucketing_and_zero_fill(db_session: Session, monkeypatch):
    monkeypatch.setattr("main.current_utc_year_month", lambda: (2025, 12))

    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("1282.37"),
                tax_amount=Decimal("105.88"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-dec.pdf",
                file_hash="hash-trend-aws-dec",
            ),
            Invoice(
                vendor="Cloudflare",
                billing_period_start=date(2025, 10, 1),
                billing_period_end=date(2025, 10, 31),
                invoice_date=date(2025, 10, 31),
                currency="USD",
                total_amount=Decimal("40.00"),
                tax_amount=Decimal("4.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/cloudflare-oct.pdf",
                file_hash="hash-trend-cloudflare-oct",
            ),
            Invoice(
                vendor="Stripe",
                billing_period_start=None,
                billing_period_end=None,
                invoice_date=date(2025, 11, 15),
                currency="EUR",
                total_amount=Decimal("70.00"),
                tax_amount=Decimal("7.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/stripe-nov.pdf",
                file_hash="hash-trend-stripe-nov",
            ),
        ]
    )
    db_session.commit()

    report = get_trend_report(months=3, db=db_session)
    assert [point.model_dump() for point in report.months] == [
        {
            "year": 2025,
            "month": 10,
            "currency": "EUR",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 10,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 40.0,
            "tax_amount_sum": 4.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "EUR",
            "invoice_count": 1,
            "total_amount_sum": 70.0,
            "tax_amount_sum": 7.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "EUR",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 1282.37,
            "tax_amount_sum": 105.88,
        },
    ]


def test_trend_report_filters_vendor_and_currency(db_session: Session, monkeypatch):
    monkeypatch.setattr("main.current_utc_year_month", lambda: (2025, 12))

    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("1282.37"),
                tax_amount=Decimal("105.88"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-dec-filter.pdf",
                file_hash="hash-trend-filter-aws-dec",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 1),
                billing_period_end=date(2025, 11, 30),
                invoice_date=date(2025, 11, 30),
                currency="USD",
                total_amount=Decimal("100.00"),
                tax_amount=Decimal("8.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-nov-filter.pdf",
                file_hash="hash-trend-filter-aws-nov",
            ),
            Invoice(
                vendor="Stripe",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="EUR",
                total_amount=Decimal("55.00"),
                tax_amount=Decimal("5.50"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/stripe-dec-filter.pdf",
                file_hash="hash-trend-filter-stripe-dec",
            ),
        ]
    )
    db_session.commit()

    vendor_filtered = get_trend_report(months=3, vendor="AWS", db=db_session)
    assert [point.model_dump() for point in vendor_filtered.months] == [
        {
            "year": 2025,
            "month": 10,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 100.0,
            "tax_amount_sum": 8.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 1282.37,
            "tax_amount_sum": 105.88,
        },
    ]

    currency_filtered = get_trend_report(months=3, currency="EUR", db=db_session)
    assert [point.model_dump() for point in currency_filtered.months] == [
        {
            "year": 2025,
            "month": 10,
            "currency": "EUR",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "EUR",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "EUR",
            "invoice_count": 1,
            "total_amount_sum": 55.0,
            "tax_amount_sum": 5.5,
        },
    ]


def test_trend_report_acceptance_current_aws_invoice_returns_prior_zero_months(db_session: Session, monkeypatch):
    monkeypatch.setattr("main.current_utc_year_month", lambda: (2025, 12))

    db_session.add(
        Invoice(
            vendor="AWS",
            billing_period_start=date(2025, 12, 1),
            billing_period_end=date(2025, 12, 31),
            invoice_date=date(2025, 12, 31),
            currency="USD",
            total_amount=Decimal("1282.37"),
            tax_amount=Decimal("105.88"),
            source=InvoiceSource.UPLOAD,
            file_path="/tmp/aws-dec-acceptance.pdf",
            file_hash="hash-trend-acceptance-aws-dec",
        )
    )
    db_session.commit()

    report = get_trend_report(months=3, db=db_session)

    assert [point.model_dump() for point in report.months] == [
        {
            "year": 2025,
            "month": 10,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 1282.37,
            "tax_amount_sum": 105.88,
        },
    ]


def test_trend_report_anchor_month_generates_expected_window(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("1282.37"),
                tax_amount=Decimal("105.88"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/aws-dec-anchor.pdf",
                file_hash="hash-trend-anchor-aws-dec",
            )
        ]
    )
    db_session.commit()

    report = get_trend_report(months=3, anchor_year=2025, anchor_month=12, db=db_session)

    assert [point.model_dump() for point in report.months] == [
        {
            "year": 2025,
            "month": 10,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 11,
            "currency": "USD",
            "invoice_count": 0,
            "total_amount_sum": 0.0,
            "tax_amount_sum": 0.0,
        },
        {
            "year": 2025,
            "month": 12,
            "currency": "USD",
            "invoice_count": 1,
            "total_amount_sum": 1282.37,
            "tax_amount_sum": 105.88,
        },
    ]


def test_trend_report_anchor_validation(db_session: Session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as missing_anchor:
        get_trend_report(months=3, anchor_year=2025, db=db_session)
    assert missing_anchor.value.status_code == 422
    assert "provided together" in missing_anchor.value.detail

    with pytest.raises(HTTPException) as invalid_anchor_month:
        get_trend_report(months=3, anchor_year=2025, anchor_month=13, db=db_session)
    assert invalid_anchor_month.value.status_code == 422
    assert "between 1 and 12" in invalid_anchor_month.value.detail


def test_anomalies_report_returns_empty_list_when_no_anomalies(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 1),
                billing_period_end=date(2025, 11, 30),
                invoice_date=date(2025, 11, 30),
                currency="USD",
                total_amount=Decimal("100.00"),
                tax_amount=Decimal("8.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-empty-aws-prev.pdf",
                file_hash="hash-anomalies-empty-aws-prev",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("110.00"),
                tax_amount=Decimal("8.80"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-empty-aws-current.pdf",
                file_hash="hash-anomalies-empty-aws-current",
            ),
        ]
    )
    db_session.commit()

    report = get_anomalies_report(year=2025, month=12, db=db_session)

    assert report.year == 2025
    assert report.month == 12
    assert report.anomalies == []


def test_anomalies_report_detects_spike_new_vendor_and_data_quality(db_session: Session):
    db_session.add_all(
        [
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 11, 1),
                billing_period_end=date(2025, 11, 30),
                invoice_date=date(2025, 11, 30),
                currency="USD",
                total_amount=Decimal("1000.00"),
                tax_amount=Decimal("80.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-aws-prev.pdf",
                file_hash="hash-anomalies-aws-prev",
            ),
            Invoice(
                vendor="AWS",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("1400.00"),
                tax_amount=Decimal("100.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-aws-current.pdf",
                file_hash="hash-anomalies-aws-current",
            ),
            Invoice(
                vendor="Cloudflare",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=Decimal("250.00"),
                tax_amount=Decimal("25.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-cloudflare-current.pdf",
                file_hash="hash-anomalies-cloudflare-current",
            ),
            Invoice(
                vendor="Datadog",
                billing_period_start=date(2025, 12, 1),
                billing_period_end=date(2025, 12, 31),
                invoice_date=date(2025, 12, 31),
                currency="USD",
                total_amount=None,
                tax_amount=Decimal("5.00"),
                source=InvoiceSource.UPLOAD,
                file_path="/tmp/anomalies-datadog-current.pdf",
                file_hash="hash-anomalies-datadog-current",
            ),
        ]
    )
    db_session.commit()

    report = get_anomalies_report(year=2025, month=12, db=db_session)
    payload = [anomaly.model_dump() for anomaly in report.anomalies]

    assert {item["type"] for item in payload} == {"spend_spike", "new_vendor", "data_quality"}

    aws_spike = next(item for item in payload if item.get("type") == "spend_spike" and item.get("vendor") == "AWS")
    assert aws_spike == {
        "type": "spend_spike",
        "vendor": "AWS",
        "currency": "USD",
        "current_total": 1400.0,
        "previous_total": 1000.0,
        "delta": 400.0,
        "pct_change": 40.0,
    }

    new_vendor = next(item for item in payload if item.get("type") == "new_vendor" and item.get("vendor") == "Cloudflare")
    assert new_vendor == {
        "type": "new_vendor",
        "vendor": "Cloudflare",
        "currency": "USD",
        "current_total": 250.0,
    }

    data_quality = next(item for item in payload if item.get("type") == "data_quality")
    assert data_quality["issue"] == "missing_total_amount"
