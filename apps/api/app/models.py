import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Numeric, String, Text, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InvoiceSource(str, enum.Enum):
    UPLOAD = "upload"
    EMAIL = "email"


class InvoiceStatus(str, enum.Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_year: Mapped[int | None] = mapped_column(nullable=True)
    report_month: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    subtotal_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[InvoiceStatus | None] = mapped_column(
        Enum(
            InvoiceStatus,
            name="invoice_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
    )
    source: Mapped[InvoiceSource] = mapped_column(
        Enum(
            InvoiceSource,
            name="invoice_source",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=InvoiceSource.UPLOAD,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    validation_errors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1", server_default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


def resolve_report_date(*, billing_period_start: date | None, invoice_date: date | None) -> date | None:
    return billing_period_start or invoice_date


@event.listens_for(Invoice, "before_insert")
@event.listens_for(Invoice, "before_update")
def set_report_period(_: object, __: object, target: Invoice) -> None:
    report_date = resolve_report_date(
        billing_period_start=target.billing_period_start,
        invoice_date=target.invoice_date,
    )
    if report_date is None:
        target.report_year = None
        target.report_month = None
        return

    target.report_year = report_date.year
    target.report_month = report_date.month
