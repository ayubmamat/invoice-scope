"""create invoices table

Revision ID: 0001_create_invoices_table
Revises: 
Create Date: 2026-02-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001_create_invoices_table"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    invoice_source = postgresql.ENUM("upload", "email", name="invoice_source", create_type=False)
    invoice_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=False),
        sa.Column("vendor_domain", sa.String(length=255), nullable=True),
        sa.Column("invoice_number", sa.String(length=255), nullable=True),
        sa.Column("billing_period_start", sa.Date(), nullable=True),
        sa.Column("billing_period_end", sa.Date(), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("source", invoice_source, nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_hash"),
    )
    op.create_index(op.f("ix_invoices_id"), "invoices", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invoices_id"), table_name="invoices")
    op.drop_table("invoices")
    postgresql.ENUM("upload", "email", name="invoice_source").drop(op.get_bind(), checkfirst=True)
