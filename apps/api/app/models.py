import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    event,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class ParserKind(str, enum.Enum):
    RULES = "rules"
    LLM = "llm"


class ParseRunStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


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
    last_parse_run_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_parse_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    parse_runs: Mapped[list["InvoiceParseRun"]] = relationship(
        back_populates="invoice",
        foreign_keys="InvoiceParseRun.invoice_id",
        order_by="InvoiceParseRun.created_at.desc()",
    )
    last_parse_run: Mapped["InvoiceParseRun | None"] = relationship(
        foreign_keys=[last_parse_run_id],
        post_update=True,
    )


class InvoiceParseRun(Base):
    __tablename__ = "invoice_parse_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_kind: Mapped[ParserKind] = mapped_column(
        Enum(
            ParserKind,
            name="parser_kind",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ParseRunStatus] = mapped_column(
        Enum(
            ParseRunStatus,
            name="parse_run_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    vendor_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_canonical: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    validation_errors: Mapped[list[str] | dict | None] = mapped_column(JSON, nullable=True)
    debug_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="parse_runs", foreign_keys=[invoice_id])


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
