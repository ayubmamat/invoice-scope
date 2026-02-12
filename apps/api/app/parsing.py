from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

MAX_TEXT_CHARS = 50_000

CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}

INVOICE_NUMBER_PATTERNS = [
    re.compile(r"\b(?:invoice\s*(?:number|no\.?|#)|inv\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE),
]

DATE_PATTERNS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%B %d, %Y",
]


@dataclass
class ParsedInvoiceData:
    vendor: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str | None = None
    total_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    billing_period_start: date | None = None
    billing_period_end: date | None = None


def extract_pdf_text(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(str(file_path))
    except Exception:
        return ""

    pages: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            pages.append(page_text)

    return "\n".join(pages)[:MAX_TEXT_CHARS]


def parse_invoice_text(text: str, filename: str | None = None) -> ParsedInvoiceData:
    normalized_text = text.strip()
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]

    parsed = ParsedInvoiceData()
    parsed.vendor = parse_vendor(lines, filename)
    parsed.invoice_number = parse_invoice_number(normalized_text)
    parsed.invoice_date = parse_labeled_date(normalized_text, ["invoice date", "date issued", "issue date", "date"])

    total_currency, total_amount = parse_labeled_amount(
        lines,
        labels=["total amount", "invoice total", "amount due", "balance due", "total due", "grand total"],
    )
    parsed.total_amount = total_amount

    tax_currency, tax_amount = parse_labeled_amount(
        lines,
        labels=["tax", "vat", "sales tax", "gst"],
    )
    parsed.tax_amount = tax_amount

    parsed.currency = parse_currency(normalized_text, [total_currency, tax_currency])

    period = parse_billing_period(normalized_text)
    if period is not None:
        parsed.billing_period_start, parsed.billing_period_end = period

    return parsed


def parse_vendor(lines: list[str], filename: str | None) -> str | None:
    for line in lines[:6]:
        low = line.lower()
        if any(token in low for token in ("invoice", "bill to", "date", "amount", "tax", "total", "invoice #")):
            continue
        if re.search(r"[A-Za-z]", line):
            return line[:255]

    if not filename:
        return None

    stem = Path(filename).stem
    cleaned = re.sub(r"[_\-.]+", " ", stem)
    tokens = [
        token
        for token in cleaned.split()
        if token.lower() not in {"invoice", "inv", "bill", "statement", "copy", "final"}
        and re.search(r"[A-Za-z]", token)
    ]
    if not tokens:
        return None

    vendor = " ".join(tokens[:4]).strip()
    return vendor[:255] if vendor else None


def parse_invoice_number(text: str) -> str | None:
    for pattern in INVOICE_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def parse_labeled_date(text: str, labels: list[str]) -> date | None:
    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}\s*[:\-]?\s*([A-Za-z0-9,\-/ ]{{6,24}})", re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group(1).strip().split("\n")[0]
        parsed = parse_date(candidate)
        if parsed:
            return parsed
    return None


def parse_labeled_amount(lines: list[str], labels: list[str]) -> tuple[str | None, Decimal | None]:
    for line in lines:
        low = line.lower()
        if not any(label in low for label in labels):
            continue
        parsed = parse_amount_with_currency(line)
        if parsed is not None:
            return parsed
    return None, None


def parse_currency(text: str, candidates: list[str | None]) -> str | None:
    for candidate in candidates:
        if candidate:
            return candidate

    match = re.search(r"\bcurrency\s*[:\-]?\s*([A-Z]{3})\b", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()

    symbols = {symbol for symbol in CURRENCY_SYMBOLS if symbol in text}
    if len(symbols) == 1:
        symbol = next(iter(symbols))
        return CURRENCY_SYMBOLS[symbol]

    return None


def parse_amount_with_currency(text: str) -> tuple[str | None, Decimal] | None:
    match = re.search(r"\b(USD|EUR|GBP|CAD|AUD|JPY|INR)\b\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", text, flags=re.IGNORECASE)
    if match:
        value = parse_decimal(match.group(2))
        if value is not None:
            return match.group(1).upper(), value

    match = re.search(r"([$€£])\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", text)
    if match:
        value = parse_decimal(match.group(2))
        if value is not None:
            return CURRENCY_SYMBOLS.get(match.group(1)), value

    match = re.search(r"\b([0-9][0-9,]*(?:\.[0-9]{2})?)\b", text)
    if match:
        value = parse_decimal(match.group(1))
        if value is not None:
            return None, value

    return None


def parse_billing_period(text: str) -> tuple[date, date] | None:
    pattern = re.compile(
        r"\b(?:billing|service)\s*period\s*[:\-]?\s*([A-Za-z0-9,\-/ ]{6,24})\s*(?:to|-)\s*([A-Za-z0-9,\-/ ]{6,24})",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None

    start = parse_date(match.group(1).strip())
    end = parse_date(match.group(2).strip())
    if start is None or end is None:
        return None
    if end < start:
        return None

    return start, end


def parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
