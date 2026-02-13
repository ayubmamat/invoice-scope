from collections import defaultdict
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import os
from typing import Annotated
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Invoice, InvoiceSource, InvoiceStatus
from app.parsing import extract_pdf_text, parse_invoice_text

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="InvoiceScope API")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
try:
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
except AssertionError:
    templates = None


PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


class SpendGroup(BaseModel):
    vendor: str
    currency: str | None
    invoice_count: int
    total_amount_sum: float
    tax_amount_sum: float


class CurrencyGrandTotal(BaseModel):
    currency: str | None
    invoice_count: int
    total_amount_sum: float
    tax_amount_sum: float


class MonthlyReportResponse(BaseModel):
    year: int
    month: int
    groups: list[SpendGroup]
    grand_totals: list[CurrencyGrandTotal]


class SpendGroupComparison(BaseModel):
    vendor: str
    currency: str | None
    invoice_count: int
    total_amount_sum: float
    tax_amount_sum: float
    prev_total_amount_sum: float | None
    prev_tax_amount_sum: float | None
    delta_total_amount: float
    delta_tax_amount: float
    pct_total_amount_change: float | None
    pct_tax_amount_change: float | None


class CurrencyGrandTotalComparison(BaseModel):
    currency: str | None
    invoice_count: int
    total_amount_sum: float
    tax_amount_sum: float
    prev_total_amount_sum: float | None
    prev_tax_amount_sum: float | None
    delta_total_amount: float
    delta_tax_amount: float
    pct_total_amount_change: float | None
    pct_tax_amount_change: float | None


class MonthlyMoMReportResponse(BaseModel):
    current: MonthlyReportResponse
    previous: MonthlyReportResponse
    groups: list[SpendGroupComparison]
    grand_totals: list[CurrencyGrandTotalComparison]


class VendorSpendGroup(BaseModel):
    vendor: str
    currency: str | None
    invoice_count: int
    total_amount_sum: float


class VendorReportResponse(BaseModel):
    vendors: list[VendorSpendGroup]


class TrendMonthPoint(BaseModel):
    year: int
    month: int
    currency: str | None
    invoice_count: int
    total_amount_sum: float
    tax_amount_sum: float


class TrendReportResponse(BaseModel):
    months: list[TrendMonthPoint]


class SpendSpikeAnomaly(BaseModel):
    type: str = "spend_spike"
    vendor: str
    currency: str | None
    current_total: float
    previous_total: float
    delta: float
    pct_change: float


class NewVendorAnomaly(BaseModel):
    type: str = "new_vendor"
    vendor: str
    currency: str | None
    current_total: float


class DataQualityAnomaly(BaseModel):
    type: str = "data_quality"
    invoice_id: int
    issue: str


class AnomaliesReportResponse(BaseModel):
    year: int
    month: int
    anomalies: list[SpendSpikeAnomaly | NewVendorAnomaly | DataQualityAnomaly]


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_storage_dir() -> Path:
    return Path(os.getenv("INVOICE_STORAGE_DIR", "/data/invoices"))


def decimal_to_float(value: Decimal | None) -> float:
    return float(value or 0)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    month_start = date(year, month, 1)
    month_end = date(year + (month // 12), (month % 12) + 1, 1)
    return month_start, month_end


def previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def iter_recent_months(*, ending_year: int, ending_month: int, months: int) -> list[tuple[int, int]]:
    year = ending_year
    month = ending_month
    values: list[tuple[int, int]] = []
    for _ in range(months):
        values.append((year, month))
        year, month = previous_year_month(year, month)
    return list(reversed(values))


def current_utc_year_month() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    return now.year, now.month


def _pct_change(current: Decimal, previous: Decimal | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return float(((current - previous) / previous) * Decimal("100"))


def month_invoice_filter(year: int, month: int):
    return and_(Invoice.report_year == year, Invoice.report_month == month)


def resolve_report_period(*, billing_period_start: date | None, invoice_date: date | None) -> tuple[int | None, int | None]:
    report_date = billing_period_start or invoice_date
    if report_date is None:
        return None, None
    return report_date.year, report_date.month


def get_month_invoices(year: int, month: int, db: Session) -> list[Invoice]:
    return db.scalars(select(Invoice).where(month_invoice_filter(year, month))).all()


def build_monthly_report(year: int, month: int, db: Session) -> MonthlyReportResponse:
    invoices = get_month_invoices(year, month, db)

    grouped: dict[tuple[str, str | None], dict[str, Decimal | int]] = {}
    grand_totals: dict[str | None, dict[str, Decimal | int]] = defaultdict(
        lambda: {"invoice_count": 0, "total_amount_sum": Decimal("0"), "tax_amount_sum": Decimal("0")}
    )

    for invoice in invoices:
        key = (invoice.vendor, invoice.currency)
        if key not in grouped:
            grouped[key] = {"invoice_count": 0, "total_amount_sum": Decimal("0"), "tax_amount_sum": Decimal("0")}

        grouped[key]["invoice_count"] += 1
        grouped[key]["total_amount_sum"] += invoice.total_amount or Decimal("0")
        grouped[key]["tax_amount_sum"] += invoice.tax_amount or Decimal("0")

        grand = grand_totals[invoice.currency]
        grand["invoice_count"] += 1
        grand["total_amount_sum"] += invoice.total_amount or Decimal("0")
        grand["tax_amount_sum"] += invoice.tax_amount or Decimal("0")

    groups = [
        SpendGroup(
            vendor=vendor,
            currency=currency,
            invoice_count=int(values["invoice_count"]),
            total_amount_sum=decimal_to_float(values["total_amount_sum"]),
            tax_amount_sum=decimal_to_float(values["tax_amount_sum"]),
        )
        for (vendor, currency), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or ""))
    ]
    grand_total_items = [
        CurrencyGrandTotal(
            currency=currency,
            invoice_count=int(values["invoice_count"]),
            total_amount_sum=decimal_to_float(values["total_amount_sum"]),
            tax_amount_sum=decimal_to_float(values["tax_amount_sum"]),
        )
        for currency, values in sorted(grand_totals.items(), key=lambda item: item[0] or "")
    ]
    return MonthlyReportResponse(year=year, month=month, groups=groups, grand_totals=grand_total_items)


def invoice_to_dict(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "vendor": invoice.vendor,
        "vendor_domain": invoice.vendor_domain,
        "invoice_number": invoice.invoice_number,
        "billing_period_start": invoice.billing_period_start,
        "billing_period_end": invoice.billing_period_end,
        "invoice_date": invoice.invoice_date,
        "report_year": invoice.report_year,
        "report_month": invoice.report_month,
        "currency": invoice.currency,
        "subtotal_amount": float(invoice.subtotal_amount) if invoice.subtotal_amount is not None else None,
        "total_amount": float(invoice.total_amount) if invoice.total_amount is not None else None,
        "tax_amount": float(invoice.tax_amount) if invoice.tax_amount is not None else None,
        "amount_paid": float(invoice.amount_paid) if invoice.amount_paid is not None else None,
        "amount_due": float(invoice.amount_due) if invoice.amount_due is not None else None,
        "status": invoice.status.value if invoice.status is not None else None,
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

    report_year, report_month = resolve_report_period(
        billing_period_start=parsed.billing_period_start,
        invoice_date=parsed.invoice_date,
    )

    invoice = Invoice(
        vendor=resolved_vendor,
        invoice_number=parsed.invoice_number,
        billing_period_start=parsed.billing_period_start,
        billing_period_end=parsed.billing_period_end,
        invoice_date=parsed.invoice_date,
        report_year=report_year,
        report_month=report_month,
        currency=parsed.currency,
        subtotal_amount=parsed.subtotal_amount,
        total_amount=parsed.total_amount,
        tax_amount=parsed.tax_amount,
        amount_paid=parsed.amount_paid,
        amount_due=parsed.amount_due,
        status=InvoiceStatus(parsed.status) if parsed.status is not None else None,
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


@app.post("/invoices/{invoice_id}/parse")
def parse_existing_invoice(
    invoice_id: int,
    force_text: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    should_extract_text = force_text or not (invoice.extracted_text or "").strip()
    extracted_text = invoice.extracted_text or ""
    if should_extract_text:
        extracted_text = extract_pdf_text(Path(invoice.file_path))

    parsed = parse_invoice_text(extracted_text)

    invoice.extracted_text = extracted_text or None
    invoice.vendor = parsed.vendor or "unknown"
    invoice.invoice_number = parsed.invoice_number
    invoice.billing_period_start = parsed.billing_period_start
    invoice.billing_period_end = parsed.billing_period_end
    invoice.invoice_date = parsed.invoice_date
    invoice.report_year, invoice.report_month = resolve_report_period(
        billing_period_start=parsed.billing_period_start,
        invoice_date=parsed.invoice_date,
    )
    invoice.currency = parsed.currency
    invoice.subtotal_amount = parsed.subtotal_amount
    invoice.total_amount = parsed.total_amount
    invoice.tax_amount = parsed.tax_amount
    invoice.amount_paid = parsed.amount_paid
    invoice.amount_due = parsed.amount_due
    invoice.status = InvoiceStatus(parsed.status) if parsed.status is not None else None

    db.commit()
    db.refresh(invoice)
    return invoice_to_dict(invoice)


@app.get("/reports/monthly", response_model=MonthlyReportResponse)
def get_monthly_report(
    year: int = Query(..., ge=1, le=9999),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> MonthlyReportResponse:
    return build_monthly_report(year=year, month=month, db=db)


@app.get("/reports/monthly/mom", response_model=MonthlyMoMReportResponse)
def get_monthly_mom_report(
    year: int = Query(..., ge=1, le=9999),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> MonthlyMoMReportResponse:
    previous_year, previous_month = previous_year_month(year, month)

    current_report = build_monthly_report(year=year, month=month, db=db)
    previous_report = build_monthly_report(year=previous_year, month=previous_month, db=db)

    current_groups = {(group.vendor, group.currency): group for group in current_report.groups}
    previous_groups = {(group.vendor, group.currency): group for group in previous_report.groups}
    all_group_keys = sorted(set(current_groups.keys()) | set(previous_groups.keys()), key=lambda item: (item[0], item[1] or ""))

    groups: list[SpendGroupComparison] = []
    for key in all_group_keys:
        vendor, currency = key
        current_group = current_groups.get(key)
        previous_group = previous_groups.get(key)

        current_total = Decimal(str(current_group.total_amount_sum)) if current_group else Decimal("0")
        current_tax = Decimal(str(current_group.tax_amount_sum)) if current_group else Decimal("0")
        previous_total = Decimal(str(previous_group.total_amount_sum)) if previous_group else None
        previous_tax = Decimal(str(previous_group.tax_amount_sum)) if previous_group else None

        groups.append(
            SpendGroupComparison(
                vendor=vendor,
                currency=currency,
                invoice_count=current_group.invoice_count if current_group else 0,
                total_amount_sum=float(current_total),
                tax_amount_sum=float(current_tax),
                prev_total_amount_sum=float(previous_total) if previous_total is not None else None,
                prev_tax_amount_sum=float(previous_tax) if previous_tax is not None else None,
                delta_total_amount=float(current_total - (previous_total or Decimal("0"))),
                delta_tax_amount=float(current_tax - (previous_tax or Decimal("0"))),
                pct_total_amount_change=_pct_change(current_total, previous_total),
                pct_tax_amount_change=_pct_change(current_tax, previous_tax),
            )
        )

    current_grand_totals = {item.currency: item for item in current_report.grand_totals}
    previous_grand_totals = {item.currency: item for item in previous_report.grand_totals}
    all_currencies = sorted(set(current_grand_totals.keys()) | set(previous_grand_totals.keys()), key=lambda item: item or "")

    grand_totals: list[CurrencyGrandTotalComparison] = []
    for currency in all_currencies:
        current_grand = current_grand_totals.get(currency)
        previous_grand = previous_grand_totals.get(currency)

        current_total = Decimal(str(current_grand.total_amount_sum)) if current_grand else Decimal("0")
        current_tax = Decimal(str(current_grand.tax_amount_sum)) if current_grand else Decimal("0")
        previous_total = Decimal(str(previous_grand.total_amount_sum)) if previous_grand else None
        previous_tax = Decimal(str(previous_grand.tax_amount_sum)) if previous_grand else None

        grand_totals.append(
            CurrencyGrandTotalComparison(
                currency=currency,
                invoice_count=current_grand.invoice_count if current_grand else 0,
                total_amount_sum=float(current_total),
                tax_amount_sum=float(current_tax),
                prev_total_amount_sum=float(previous_total) if previous_total is not None else None,
                prev_tax_amount_sum=float(previous_tax) if previous_tax is not None else None,
                delta_total_amount=float(current_total - (previous_total or Decimal("0"))),
                delta_tax_amount=float(current_tax - (previous_tax or Decimal("0"))),
                pct_total_amount_change=_pct_change(current_total, previous_total),
                pct_tax_amount_change=_pct_change(current_tax, previous_tax),
            )
        )

    return MonthlyMoMReportResponse(
        current=current_report,
        previous=previous_report,
        groups=groups,
        grand_totals=grand_totals,
    )


@app.get("/reports/anomalies", response_model=AnomaliesReportResponse)
def get_anomalies_report(
    year: int = Query(..., ge=1, le=9999),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> AnomaliesReportResponse:
    previous_year, previous_month = previous_year_month(year, month)

    current_report = build_monthly_report(year=year, month=month, db=db)
    previous_report = build_monthly_report(year=previous_year, month=previous_month, db=db)

    current_groups = {(group.vendor, group.currency): group for group in current_report.groups}
    previous_groups = {(group.vendor, group.currency): group for group in previous_report.groups}

    anomalies: list[SpendSpikeAnomaly | NewVendorAnomaly | DataQualityAnomaly] = []

    for key in sorted(current_groups.keys(), key=lambda item: (item[0], item[1] or "")):
        current_group = current_groups[key]
        previous_group = previous_groups.get(key)

        current_total = Decimal(str(current_group.total_amount_sum))
        if previous_group is None:
            anomalies.append(
                NewVendorAnomaly(
                    vendor=current_group.vendor,
                    currency=current_group.currency,
                    current_total=current_group.total_amount_sum,
                )
            )
            continue

        previous_total = Decimal(str(previous_group.total_amount_sum))
        if previous_total <= 0:
            continue

        delta = current_total - previous_total
        pct_change = (delta / previous_total) * Decimal("100")
        if pct_change >= Decimal("30"):
            anomalies.append(
                SpendSpikeAnomaly(
                    vendor=current_group.vendor,
                    currency=current_group.currency,
                    current_total=current_group.total_amount_sum,
                    previous_total=previous_group.total_amount_sum,
                    delta=decimal_to_float(delta),
                    pct_change=decimal_to_float(pct_change),
                )
            )

    for invoice in get_month_invoices(year, month, db):
        if invoice.total_amount is None:
            anomalies.append(DataQualityAnomaly(invoice_id=invoice.id, issue="missing_total_amount"))
        if invoice.currency is None:
            anomalies.append(DataQualityAnomaly(invoice_id=invoice.id, issue="missing_currency"))
        if invoice.report_year is None or invoice.report_month is None:
            anomalies.append(DataQualityAnomaly(invoice_id=invoice.id, issue="missing_report_period"))

    return AnomaliesReportResponse(year=year, month=month, anomalies=anomalies)


@app.post("/dev/seed")
def seed_dev_data(db: Session = Depends(get_db)) -> dict[str, int | str]:
    if os.getenv("ENV") != "dev":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    current_start, current_end = month_bounds(date.today().year, date.today().month)
    previous_year, previous_month = previous_year_month(date.today().year, date.today().month)
    prev_start, prev_end = month_bounds(previous_year, previous_month)

    seed_specs = [
        {
            "month_start": prev_start,
            "month_end": prev_end,
            "total_amount": Decimal("1000.00"),
            "tax_amount": Decimal("80.00"),
            "file_hash": f"dev-seed-aws-{prev_start.year:04d}{prev_start.month:02d}",
        },
        {
            "month_start": current_start,
            "month_end": current_end,
            "total_amount": Decimal("1282.37"),
            "tax_amount": Decimal("105.88"),
            "file_hash": f"dev-seed-aws-{current_start.year:04d}{current_start.month:02d}",
        },
    ]

    created = 0
    reused = 0
    for spec in seed_specs:
        existing = db.scalar(select(Invoice).where(Invoice.file_hash == spec["file_hash"]))
        if existing is not None:
            reused += 1
            continue

        invoice = Invoice(
            vendor="AWS",
            currency="USD",
            billing_period_start=spec["month_start"],
            billing_period_end=spec["month_end"] - timedelta(days=1),
            invoice_date=spec["month_end"] - timedelta(days=1),
            report_year=spec["month_start"].year,
            report_month=spec["month_start"].month,
            subtotal_amount=spec["total_amount"] - spec["tax_amount"],
            total_amount=spec["total_amount"],
            tax_amount=spec["tax_amount"],
            amount_due=spec["total_amount"],
            status=InvoiceStatus.UNKNOWN,
            source=InvoiceSource.UPLOAD,
            file_path=f"/dev/seed/{spec['file_hash']}.pdf",
            file_hash=spec["file_hash"],
        )
        db.add(invoice)
        created += 1

    db.commit()
    return {"status": "ok", "created": created, "reused": reused}


@app.get("/reports/vendors", response_model=VendorReportResponse)
def get_vendor_report(db: Session = Depends(get_db)) -> VendorReportResponse:
    invoices = db.scalars(select(Invoice)).all()
    grouped: dict[tuple[str, str | None], dict[str, Decimal | int]] = {}

    for invoice in invoices:
        key = (invoice.vendor, invoice.currency)
        if key not in grouped:
            grouped[key] = {"invoice_count": 0, "total_amount_sum": Decimal("0")}
        grouped[key]["invoice_count"] += 1
        grouped[key]["total_amount_sum"] += invoice.total_amount or Decimal("0")

    vendors = [
        VendorSpendGroup(
            vendor=vendor,
            currency=currency,
            invoice_count=int(values["invoice_count"]),
            total_amount_sum=decimal_to_float(values["total_amount_sum"]),
        )
        for (vendor, currency), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or ""))
    ]
    return VendorReportResponse(vendors=vendors)


@app.get("/reports/trend", response_model=TrendReportResponse)
def get_trend_report(
    months: int = Query(default=6, ge=1, le=24),
    vendor: str | None = None,
    currency: str | None = None,
    anchor_year: Annotated[int | None, Query(ge=1, le=9999)] = None,
    anchor_month: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
) -> TrendReportResponse:
    if (anchor_year is None) != (anchor_month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="anchor_year and anchor_month must be provided together",
        )
    if anchor_month is not None and not 1 <= anchor_month <= 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="anchor_month must be between 1 and 12",
        )

    if anchor_year is not None and anchor_month is not None:
        ending_year, ending_month = anchor_year, anchor_month
    else:
        ending_year, ending_month = current_utc_year_month()

    month_keys = iter_recent_months(ending_year=ending_year, ending_month=ending_month, months=months)

    filters = [
        Invoice.report_year.is_not(None),
        Invoice.report_month.is_not(None),
        or_(*[and_(Invoice.report_year == year, Invoice.report_month == month) for year, month in month_keys]),
    ]
    if vendor is not None:
        filters.append(Invoice.vendor == vendor)
    if currency is not None:
        filters.append(Invoice.currency == currency)

    invoices = db.scalars(select(Invoice).where(*filters)).all()

    grouped: dict[tuple[int, int, str | None], dict[str, Decimal | int]] = defaultdict(
        lambda: {"invoice_count": 0, "total_amount_sum": Decimal("0"), "tax_amount_sum": Decimal("0")}
    )
    currencies_seen: set[str | None] = set()

    for invoice in invoices:
        if invoice.report_year is None or invoice.report_month is None:
            continue

        key = (invoice.report_year, invoice.report_month, invoice.currency)
        grouped[key]["invoice_count"] += 1
        grouped[key]["total_amount_sum"] += invoice.total_amount or Decimal("0")
        grouped[key]["tax_amount_sum"] += invoice.tax_amount or Decimal("0")
        currencies_seen.add(invoice.currency)

    if currency is not None:
        currencies = [currency]
    else:
        currencies = sorted(currencies_seen, key=lambda value: value or "")

    points: list[TrendMonthPoint] = []
    for year, month in month_keys:
        if not currencies:
            points.append(
                TrendMonthPoint(
                    year=year,
                    month=month,
                    currency=currency,
                    invoice_count=0,
                    total_amount_sum=0,
                    tax_amount_sum=0,
                )
            )
            continue

        for month_currency in currencies:
            values = grouped[(year, month, month_currency)]
            points.append(
                TrendMonthPoint(
                    year=year,
                    month=month,
                    currency=month_currency,
                    invoice_count=int(values["invoice_count"]),
                    total_amount_sum=decimal_to_float(values["total_amount_sum"]),
                    tax_amount_sum=decimal_to_float(values["tax_amount_sum"]),
                )
            )

    return TrendReportResponse(months=points)


def _truncate_text(text: str | None, limit: int = 20000) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n\n... [truncated {len(value) - limit} chars]"


def render_dashboard(request: Request, months: int, db: Session) -> HTMLResponse:
    year, month = current_utc_year_month()
    monthly_report = build_monthly_report(year=year, month=month, db=db)
    mom_report = get_monthly_mom_report(year=year, month=month, db=db)
    anomalies = get_anomalies_report(year=year, month=month, db=db)
    trend = get_trend_report(months=months, anchor_year=year, anchor_month=month, db=db)

    if templates is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Jinja2 is not installed")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "year": year,
            "month": month,
            "months": months,
            "monthly_report": monthly_report,
            "mom_report": mom_report,
            "anomalies": anomalies.anomalies,
            "trend": trend.months,
        },
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, months: int = Query(default=6, ge=1, le=24), db: Session = Depends(get_db)) -> HTMLResponse:
    return render_dashboard(request=request, months=months, db=db)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, months: int = Query(default=6, ge=1, le=24), db: Session = Depends(get_db)) -> HTMLResponse:
    return render_dashboard(request=request, months=months, db=db)


@app.get("/ui/invoices", response_class=HTMLResponse)
def invoices_ui(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if templates is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Jinja2 is not installed")

    invoices = db.scalars(select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(200)).all()
    return templates.TemplateResponse(request=request, name="invoice_list.html", context={"request": request, "invoices": invoices})


@app.get("/ui/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_detail_ui(invoice_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if templates is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Jinja2 is not installed")

    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    invoice_json = json.dumps(invoice_to_dict(invoice), default=str, indent=2)
    return templates.TemplateResponse(
        request=request,
        name="invoice_detail.html",
        context={
            "request": request,
            "invoice": invoice,
            "invoice_json": invoice_json,
            "extracted_text": _truncate_text(invoice.extracted_text),
        },
    )
