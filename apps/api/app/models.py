import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InvoiceSource(str, enum.Enum):
    UPLOAD = "upload"
    EMAIL = "email"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source: Mapped[InvoiceSource] = mapped_column(
        Enum(InvoiceSource, name="invoice_source"),
        nullable=False,
        default=InvoiceSource.UPLOAD,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
