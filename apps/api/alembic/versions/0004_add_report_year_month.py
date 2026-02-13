"""add report year/month fields to invoices

Revision ID: 0004_add_report_year_month
Revises: 0003_add_financial_v2_fields
Create Date: 2026-02-13 00:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_add_report_year_month"
down_revision: Union[str, None] = "0003_add_financial_v2_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("report_year", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("report_month", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE invoices
        SET
            report_year = EXTRACT(YEAR FROM COALESCE(billing_period_start, invoice_date))::integer,
            report_month = EXTRACT(MONTH FROM COALESCE(billing_period_start, invoice_date))::integer
        WHERE COALESCE(billing_period_start, invoice_date) IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("invoices", "report_month")
    op.drop_column("invoices", "report_year")
