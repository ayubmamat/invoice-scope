"""add financial model v2 fields to invoices

Revision ID: 0003_add_financial_v2_fields
Revises: 0002_add_extracted_text_to_invoices
Create Date: 2026-02-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0003_add_financial_v2_fields"
down_revision: Union[str, None] = "0002_add_extracted_text_to_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INVOICE_STATUS = postgresql.ENUM("PAID", "UNPAID", "PARTIAL", "UNKNOWN", name="invoice_status", create_type=False)


def upgrade() -> None:
    INVOICE_STATUS.create(op.get_bind(), checkfirst=True)

    op.add_column("invoices", sa.Column("subtotal_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("invoices", sa.Column("amount_paid", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("invoices", sa.Column("amount_due", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("invoices", sa.Column("status", INVOICE_STATUS, nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "status")
    op.drop_column("invoices", "amount_due")
    op.drop_column("invoices", "amount_paid")
    op.drop_column("invoices", "subtotal_amount")

    INVOICE_STATUS.drop(op.get_bind(), checkfirst=True)
