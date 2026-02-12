import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import date
from decimal import Decimal
from app.parsing import parse_invoice_text


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_invoice_text.txt"


AWS_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "aws_tax_invoice_text.txt"


def test_parse_invoice_text_fixture():
    text = FIXTURE_PATH.read_text(encoding="utf-8")

    parsed = parse_invoice_text(text, filename="acme_invoice_jan.pdf")

    assert parsed.vendor == "Acme Cloud Services"
    assert parsed.invoice_number == "INV-2025-0042"
    assert parsed.invoice_date == date(2025, 1, 15)
    assert parsed.billing_period_start == date(2024, 12, 1)
    assert parsed.billing_period_end == date(2024, 12, 31)
    assert parsed.currency == "USD"
    assert parsed.total_amount == Decimal("1080.00")
    assert parsed.tax_amount == Decimal("80.00")


def test_parse_invoice_text_conservative_when_missing_fields():
    parsed = parse_invoice_text("Invoice\nHello there\nNo totals here", filename="unknown.pdf")

    assert parsed.invoice_number is None
    assert parsed.invoice_date is None
    assert parsed.total_amount is None
    assert parsed.tax_amount is None


def test_parse_invoice_text_aws_tax_invoice_fixture():
    text = AWS_FIXTURE_PATH.read_text(encoding="utf-8")

    parsed = parse_invoice_text(text, filename="aws_tax_invoice.pdf")

    assert parsed.vendor == "AWS"
    assert parsed.invoice_number == "SGIN26-10731"
    assert parsed.invoice_date == date(2026, 1, 1)
    assert parsed.currency == "USD"
    assert parsed.total_amount == Decimal("1282.37")
    assert parsed.billing_period_start == date(2025, 12, 1)
    assert parsed.billing_period_end == date(2025, 12, 31)
    assert parsed.tax_amount is None
