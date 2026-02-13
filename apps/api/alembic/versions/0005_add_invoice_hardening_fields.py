"""add invoice hardening fields

Revision ID: 0005_add_invoice_hardening_fields
Revises: 0004_add_report_year_month
Create Date: 2026-02-13 01:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_add_invoice_hardening_fields"
down_revision: Union[str, None] = "0004_add_report_year_month"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("vendor_raw", sa.String(length=255), nullable=True))
    op.add_column("invoices", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("invoices", sa.Column("validation_errors", sa.JSON(), nullable=True))
    op.add_column("invoices", sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("parser_version", sa.String(length=32), nullable=False, server_default="v1"))

    op.execute("UPDATE invoices SET vendor_raw = vendor WHERE vendor_raw IS NULL")


def downgrade() -> None:
    op.drop_column("invoices", "parser_version")
    op.drop_column("invoices", "parsed_at")
    op.drop_column("invoices", "validation_errors")
    op.drop_column("invoices", "needs_review")
    op.drop_column("invoices", "vendor_raw")
