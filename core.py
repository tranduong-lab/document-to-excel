"""Document reading, invoice extraction, checks and Excel export (shared by app and CLI)."""
import io
import re
from dataclasses import dataclass, field

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

YELLOW = PatternFill("solid", fgColor="FFF2A8")
RED = PatternFill("solid", fgColor="F8C9C4")
GREEN = PatternFill("solid", fgColor="CDEBC9")
HEAD = PatternFill("solid", fgColor="1F3A5F")
MONEY = r"(\d[\d,]*\.\d{2})"
MIN_TEXT_CHARS = 40


@dataclass
class Page:
    number: int
    text: str
    method: str


@dataclass
class Result:
    columns: list
    rows: list
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    extra_sheets: dict = field(default_factory=dict)
    summary: list = field(default_factory=list)


def read_document(data: bytes, filename: str, ocr_lang="eng") -> list[Page]:
    if filename.lower().endswith(".pdf"):
        pages = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages]
        images = None
        for i, t in enumerate(texts, 1):
            if len(t.strip()) >= MIN_TEXT_CHARS:
                pages.append(Page(i, t, "text layer"))
            else:
                images = images or convert_from_bytes(data, dpi=200)
                pages.append(Page(i, pytesseract.image_to_string(images[i - 1], lang=ocr_lang, config="--psm 6"), "OCR"))
        return pages
    img = Image.open(io.BytesIO(data))
    return [Page(1, pytesseract.image_to_string(img, lang=ocr_lang, config="--psm 6"), "OCR")]


def _num(s):
    return float(s.replace(",", "")) if s else None


def _grab(pattern, text):
    m = re.search(pattern, text, re.I | re.M)
    return m.group(1).strip() if m else None


def parse_invoice(page: Page):
    text = page.text
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rec = {
        "Page": page.number,
        "Invoice No": _grab(r"Invoice\s*(?:No|Number|#)\.?:?\s*([A-Z0-9][A-Z0-9-]{3,})", text),
        "Date": _grab(r"(?:Invoice\s*)?Date:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", text),
        "Vendor": re.sub(r"\s*INVOICE$", "", lines[0], flags=re.I) if lines else None,
        "Subtotal": _num(_grab(r"Subtotal:?\s*\$?" + MONEY, text)),
        "Tax": _num(_grab(r"^\s*Tax\b.*?:?\s*\$?" + MONEY, text)),
        "Total": _num(_grab(r"^\s*(?:TOTAL|Amount Due|Total Due):?\s*\$?" + MONEY, text)),
    }
    items = []
    for l in lines:
        m = re.match(r"(.+?)\s+(\S{1,3})\s+\$?" + MONEY + r"\s+\$?" + MONEY + r"$", l)
        if m and not re.match(r"(subtotal|tax|total)", l, re.I):
            q = m.group(2)
            items.append({"Page": page.number, "Invoice No": rec["Invoice No"], "Description": m.group(1),
                          "Qty": int(q) if q.isdigit() else None, "Qty (as read)": q,
                          "Unit Price": _num(m.group(3)), "Amount": _num(m.group(4))})
    return rec, items


def check_invoice(rec, items):
    issues = {}
    for f in ("Invoice No", "Date", "Subtotal", "Total"):
        if rec[f] is None:
            issues[f] = "not readable - please confirm"
    if rec["Subtotal"] is not None and items:
        s = round(sum(i["Amount"] for i in items), 2)
        if abs(s - rec["Subtotal"]) > 0.01:
            issues["Subtotal"] = f"line items add up to {s:,.2f}"
    if None not in (rec["Subtotal"], rec["Tax"], rec["Total"]) and abs(rec["Subtotal"] + rec["Tax"] - rec["Total"]) > 0.01:
        issues["Total"] = "subtotal + tax does not equal total"
    for i in items:
        if i["Qty"] is None:
            issues.setdefault("Line items", f"qty unreadable on '{i['Description']}' (read as '{i['Qty (as read)']}')")
        elif abs(i["Qty"] * i["Unit Price"] - i["Amount"]) > 0.01:
            issues.setdefault("Line items", f"'{i['Description']}': qty x price does not equal amount")
    return issues


def extract_invoices(pages: list[Page]) -> Result:
    cols = ["Page", "Invoice No", "Date", "Vendor", "Subtotal", "Tax", "Total", "Status", "Notes", "Read by"]
    rows, flags, notes, all_items = [], [], [], []
    for p in pages:
        rec, items = parse_invoice(p)
        issues = check_invoice(rec, items)
        rec.update({"Status": "CHECK" if issues else "OK",
                    "Notes": "; ".join(f"{k}: {v}" for k, v in issues.items()), "Read by": p.method})
        rows.append([rec[c] for c in cols])
        flags.append({c for c in issues if c in cols})
        all_items += items
    item_cols = ["Page", "Invoice No", "Description", "Qty", "Unit Price", "Amount"]
    checked = sum(1 for r in rows if r[7] == "CHECK")
    summary = [("Pages processed", len(pages)), ("Invoices OK", len(rows) - checked),
               ("Invoices to confirm", checked), ("Line items extracted", len(all_items)),
               ("Sum of extracted totals", round(sum(r[6] or 0 for r in rows), 2)),
               ("Rule", "Unreadable or inconsistent values are highlighted, never guessed")]
    return Result(cols, rows, flags, notes,
                  {"Line Items": (item_cols, [[i[c] for c in item_cols] for i in all_items],
                                  [{"Qty"} if i["Qty"] is None else set() for i in all_items])},
                  summary)


def _sheet(ws, headers, rows, flags=None):
    ws.append(headers)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), HEAD, Alignment(horizontal="center")
    for r_i, r in enumerate(rows, 2):
        ws.append(r)
        for c_i, v in enumerate(r, 1):
            if isinstance(v, float):
                ws.cell(r_i, c_i).number_format = "#,##0.00"
        for col in (flags[r_i - 2] if flags else ()):
            ws.cell(r_i, headers.index(col) + 1).fill = YELLOW
        if "Status" in headers:
            s = ws.cell(r_i, headers.index("Status") + 1)
            s.fill = GREEN if s.value == "OK" else RED
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
    ws.freeze_panes = "A2"


def to_excel(result: Result, main_title="Results") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = main_title
    _sheet(ws, result.columns, result.rows, result.flags)
    for name, (cols, rows, flags) in result.extra_sheets.items():
        _sheet(wb.create_sheet(name), cols, rows, flags)
    _sheet(wb.create_sheet("Check Report"), ["Check", "Result"], [list(s) for s in result.summary])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
