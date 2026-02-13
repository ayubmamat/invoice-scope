"""add invoice parse runs

Revision ID: 0006_add_invoice_parse_runs
Revises: 0005_add_invoice_hardening_fields
Create Date: 2026-02-13 02:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0006_add_invoice_parse_runs"
down_revision: Union[str, None] = "0005_add_invoice_hardening_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


parser_kind_enum = postgresql.ENUM("rules", "llm", name="parser_kind", create_type=False)
parse_run_status_enum = postgresql.ENUM(
    "success",
    "failed",
    "needs_review",
    name="parse_run_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    parser_kind_enum.create(bind, checkfirst=True)
    parse_run_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "invoice_parse_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("parser_kind", parser_kind_enum, nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("status", parse_run_status_enum, nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("vendor_raw", sa.String(length=255), nullable=True),
        sa.Column("vendor_canonical", sa.String(length=255), nullable=True),
        sa.Column("invoice_number", sa.String(length=255), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("billing_period_start", sa.Date(), nullable=True),
        sa.Column("billing_period_end", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("debug_info", sa.JSON(), nullable=True),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_invoice_parse_runs_confidence_range"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_parse_runs_invoice_id", "invoice_parse_runs", ["invoice_id"], unique=False)

    op.add_column("invoices", sa.Column("last_parse_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_invoices_last_parse_run_id",
        "invoices",
        "invoice_parse_runs",
        ["last_parse_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoices_last_parse_run_id", "invoices", type_="foreignkey")
    op.drop_column("invoices", "last_parse_run_id")

    op.drop_index("ix_invoice_parse_runs_invoice_id", table_name="invoice_parse_runs")
    op.drop_table("invoice_parse_runs")

    bind = op.get_bind()
    parse_run_status_enum.drop(bind, checkfirst=True)
    parser_kind_enum.drop(bind, checkfirst=True)
