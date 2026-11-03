import os
from pathlib import Path

import pandas as pd
import streamlit as st

from core import extract_invoices, read_document, to_excel

SAMPLES = Path(__file__).parent / "samples"
YELLOW = "background-color:#FFF2A8"
AI_ENABLED = os.environ.get("ENABLE_AI") == "1"

st.set_page_config(page_title="Document → Excel Extractor", page_icon="📄", layout="wide")
st.title("Document → Checked Excel")
st.caption("Upload scanned or digital PDFs / images. Data is extracted, cross-checked, and anything unclear "
           "is highlighted for you to confirm, never guessed. Files are processed in memory and not stored.")

with st.sidebar:
    st.header("Settings")
    modes = ["Invoices (built-in rules)"] + (["Custom fields (AI, needs API key)"] if AI_ENABLED else [])
    mode = st.radio("Extraction mode", modes) if len(modes) > 1 else modes[0]
    ocr_lang = st.selectbox("OCR language", ["eng", "vie", "eng+vie"], help="Used only for scanned pages")
    if mode.startswith("Custom"):
        api_key = st.text_input("Anthropic API key", type="password", help="Used only for this session")
        model = st.text_input("Model", "claude-sonnet-5-5")
        fields_raw = st.text_area("Fields to extract (one per line)", "Invoice No\nInvoice Date\nVendor\nTotal")
    st.divider()
    st.markdown("Built by **Duong Tran** · document data extraction & Excel automation")

src = st.radio("Input", ["Use a sample file", "Upload my own"], horizontal=True)
files = []
if src == "Use a sample file":
    choice = st.selectbox("Sample (fictional data)", sorted(p.name for p in SAMPLES.glob("*.pdf")))
    files = [(choice, (SAMPLES / choice).read_bytes())]
else:
    up = st.file_uploader("PDF, PNG or JPG", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
    files = [(f.name, f.getvalue()) for f in up or []]

if files and st.button("Extract", type="primary"):
    pages, offset = [], 0
    with st.spinner("Reading documents..."):
        for name, data in files:
            for p in read_document(data, name, ocr_lang):
                p.number += offset
                pages.append(p)
            offset = len(pages)
    try:
        with st.spinner("Extracting and checking..."):
            if mode.startswith("Invoices"):
                result, title = extract_invoices(pages), "Invoices"
            else:
                from ai_extract import extract_fields
                names = [f.strip() for f in fields_raw.splitlines() if f.strip()]
                if not api_key or not names:
                    st.error("Enter an API key and at least one field.")
                    st.stop()
                result, title = extract_fields(pages, names, api_key, model), "Fields"
    except Exception as e:
        st.error(f"Extraction failed: {e}")
        st.stop()
    st.session_state.update(result=result, title=title, pages=pages)

if "result" in st.session_state:
    r, title = st.session_state.result, st.session_state.title
    status = r.columns.index("Status")
    ok = sum(1 for row in r.rows if row[status] == "OK")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pages", len(st.session_state.pages))
    c2.metric("OK", ok)
    c3.metric("To confirm", len(r.rows) - ok)

    show = lambda v: "—" if v is None else f"{v:,.2f}" if isinstance(v, float) else str(v)
    df = pd.DataFrame([[show(v) for v in row] for row in r.rows], columns=r.columns)

    def paint(row):
        f = r.flags[row.name]
        return [YELLOW if c in f else ("color:#2f7d4a;font-weight:600" if c == "Status" and v == "OK" else
                ("color:#b3412f;font-weight:600" if c == "Status" else "")) for c, v in row.items()]

    st.subheader(title)
    st.dataframe(df.style.apply(paint, axis=1), width="stretch", hide_index=True)
    for name, (cols, rows, _) in r.extra_sheets.items():
        with st.expander(f"{name} ({len(rows)})"):
            st.dataframe(pd.DataFrame(rows, columns=cols), width="stretch", hide_index=True)
    with st.expander("Raw text per page"):
        for p in st.session_state.pages:
            st.text_area(f"Page {p.number} · {p.method}", p.text, height=150)
    st.download_button("Download Excel", to_excel(r, title), file_name=f"{title.lower()}_extracted.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
