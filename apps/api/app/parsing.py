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
    parsed.vendor = parse_vendor(lines, normalized_text)
    parsed.invoice_number = parse_invoice_number(normalized_text)
    parsed.invoice_date = parse_labeled_date(normalized_text, ["invoice date", "date issued", "issue date", "date"])

    total_currency, total_amount = parse_total_amount(lines)
    parsed.total_amount = total_amount

    tax_currency, tax_amount = parse_tax_amount(normalized_text, lines)
    parsed.tax_amount = tax_amount

    parsed.currency = parse_currency(normalized_text, [total_currency, tax_currency])

    period = parse_billing_period(normalized_text)
    if period is not None:
        parsed.billing_period_start, parsed.billing_period_end = period

    return parsed


def parse_vendor(lines: list[str], text: str) -> str | None:
    low_text = text.lower()
    if any(token in low_text for token in ("console.aws.amazon.com", "amazon web services", "aws service charges")):
        return "AWS"

    for line in lines[:6]:
        low = line.lower()
        if any(token in low for token in ("invoice", "bill to", "date", "amount", "tax", "total", "invoice #")):
            continue
        if not re.search(r"[A-Za-z]", line):
            continue
        if len(line) > 80 or len(line.split()) > 8:
            continue
        return line[:255]

    return "unknown"


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
        if is_excluded_tax_line(low):
            continue
        if not any(label in low for label in labels):
            continue
        parsed = parse_amount_with_currency(line)
        if parsed is not None:
            return parsed
    return None, None


def parse_tax_amount(text: str, lines: list[str]) -> tuple[str | None, Decimal | None]:
    compact_text = re.sub(r"\s+", " ", text)

    gst_total_match = re.search(r"\btotal\s+(?:sg\s+)?gst\s+amount\b", compact_text, flags=re.IGNORECASE)
    if gst_total_match:
        lookahead = compact_text[gst_total_match.end() : gst_total_match.end() + 100]
        parsed = parse_amount_with_currency(lookahead)
        if parsed is not None and parsed[0] == "USD":
            return parsed

    gst_line_matches = re.findall(
        r"\bsg\s+gst\s+usd\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
        compact_text,
        flags=re.IGNORECASE,
    )
    if gst_line_matches:
        gst_total = Decimal("0.00")
        for raw_value in gst_line_matches:
            value = parse_decimal(raw_value)
            if value is not None:
                gst_total += value
        return "USD", gst_total.quantize(Decimal("0.01"))

    return parse_labeled_amount(
        lines,
        labels=["tax", "vat", "sales tax", "gst"],
    )


def is_excluded_tax_line(low_line: str) -> bool:
    return "excl" in low_line and "tax" in low_line


def parse_total_amount(lines: list[str]) -> tuple[str | None, Decimal | None]:
    for index, line in enumerate(lines):
        if "total amount due" not in line.lower():
            continue

        search_lines = lines[index : index + 6]
        for candidate in search_lines:
            parsed = parse_amount_with_currency(candidate)
            if parsed is not None:
                return parsed

    return parse_labeled_amount(
        lines,
        labels=["total amount", "invoice total", "amount due", "balance due", "total due", "grand total"],
    )


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

    match = re.search(r"(?<![A-Za-z0-9\-])([0-9][0-9,]*(?:\.[0-9]{2}))(?![A-Za-z0-9\-])", text)
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

    start_text = match.group(1).strip()
    end_text = match.group(2).strip()

    start = parse_date(start_text)
    end = parse_date(end_text)

    if start is None and end is not None:
        start = parse_date(f"{start_text}, {end.year}")
    if end is None and start is not None:
        end = parse_date(f"{end_text}, {start.year}")
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
