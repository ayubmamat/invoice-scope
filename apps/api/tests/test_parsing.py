import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import date
from decimal import Decimal
from app.parsing import parse_invoice_text


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_invoice_text.txt"
AWS_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "aws_tax_invoice_text.txt"
AZURE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "azure_invoice_text.txt"
FRESHDESK_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "freshdesk_invoice_text.txt"


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


def test_parse_invoice_text_aws_tax_invoice_regression_fixture():
    text = AWS_FIXTURE_PATH.read_text(encoding="utf-8")

    parsed = parse_invoice_text(text, filename="aws_tax_invoice.pdf")

    assert parsed.vendor == "AWS"
    assert parsed.invoice_number == "SGIN26-10731"
    assert parsed.invoice_date == date(2026, 1, 1)
    assert parsed.currency == "USD"
    assert parsed.total_amount == Decimal("1282.37")
    assert parsed.billing_period_start == date(2025, 12, 1)
    assert parsed.billing_period_end == date(2025, 12, 31)
    assert parsed.tax_amount == Decimal("105.88")
    assert parsed.tax_amount != Decimal("1176.49")
    assert parsed.amount_due == Decimal("1282.37")
    assert parsed.status == "UNKNOWN"


def test_parse_invoice_text_azure_fixture():
    text = AZURE_FIXTURE_PATH.read_text(encoding="utf-8")

    parsed = parse_invoice_text(text, filename="azure_tax_invoice.pdf")

    assert parsed.vendor == "Microsoft Azure"
    assert parsed.invoice_number == "G139702701"
    assert parsed.invoice_date == date(2026, 2, 9)
    assert parsed.billing_period_start == date(2026, 1, 1)
    assert parsed.billing_period_end == date(2026, 1, 31)
    assert parsed.currency == "USD"
    assert parsed.subtotal_amount == Decimal("0.50")
    assert parsed.total_amount == Decimal("0.55")
    assert parsed.tax_amount == Decimal("0.05")
    assert parsed.status == "UNKNOWN"


def test_parse_invoice_text_freshdesk_fixture():
    text = FRESHDESK_FIXTURE_PATH.read_text(encoding="utf-8")

    parsed = parse_invoice_text(text, filename="freshdesk_invoice.pdf")

    assert parsed.vendor == "Freshdesk"
    assert parsed.invoice_number == "FD2581504"
    assert parsed.invoice_date == date(2026, 1, 13)
    assert parsed.billing_period_start == date(2026, 1, 13)
    assert parsed.billing_period_end == date(2026, 2, 13)
    assert parsed.currency == "USD"
    assert parsed.subtotal_amount == Decimal("234.00")
    assert parsed.total_amount == Decimal("234.00")
    assert parsed.amount_paid == Decimal("234.00")
    assert parsed.amount_due == Decimal("0.00")
    assert parsed.status == "PAID"
    assert parsed.tax_amount is None


def test_vendor_detection_snippets_aws_azure_freshdesk():
    aws_text = """
    Tax Invoice
    Amazon Web Services, Inc.
    Invoice Number: AWS-INV-100
    Invoice Date: 2026-01-01
    Total Amount Due USD 120.00
    """
    azure_text = """
    Microsoft
    Billing Summary
    Tax Invoice Number G123456789
    Tax Invoice Date 09/02/2026
    Total (including Tax) USD 20.00
    Tax 1.00
    """
    freshdesk_text = """
    Freshworks Inc.
    Invoice #—FD2581504
    Invoice Date — Jan 13, 2026
    Invoice Amount — $ 234.00 (USD)
    Amount Due — $ 234.00 (USD)
    """

    assert parse_invoice_text(aws_text).vendor == "AWS"
    assert parse_invoice_text(azure_text).vendor == "Microsoft Azure"
    assert parse_invoice_text(freshdesk_text).vendor == "Freshdesk"


def test_vendor_detection_unknown_fallback():
    parsed = parse_invoice_text("Invoice\nInvoice Date: 2026-01-01\nTotal Amount: USD 10.00")

    assert parsed.vendor == "unknown"
