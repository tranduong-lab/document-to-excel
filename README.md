# Document → Checked Excel (Streamlit demo)

**Live demo: https://duong-doc-to-excel.streamlit.app**

![App screenshot](docs/screenshot.png)

Upload scanned or digital PDFs / images → OCR (scanned pages only) → extraction → cross-checks → Excel download.

- **Invoices mode** (no API key): invoice no, date, vendor, subtotal, tax, total, line items. Checks line items vs subtotal, subtotal + tax vs total, unreadable values.
- **Custom fields mode** (optional, hidden in the public demo; enable with env `ENABLE_AI=1` + an Anthropic API key): every value must come with an exact quote from the page; unverified values are highlighted.
- Digital PDFs use the text layer (exact); scanned pages fall back to Tesseract OCR (eng / vie).
- Sample files in `samples/` are fictional.

## Run locally
```
sudo apt install tesseract-ocr tesseract-ocr-vie poppler-utils   # Windows: install Tesseract + Poppler and add to PATH
pip install -r requirements.txt
streamlit run app.py
```

## Deploy free on Streamlit Community Cloud
1. Push this folder to a public GitHub repo (`requirements.txt` and `packages.txt` at the repo root).
2. share.streamlit.io → Create app → pick the repo, main file `app.py` → Deploy.
3. Put the app link in your Upwork profile and proposals.

## n8n workflow: email PDF invoices → validated Google Sheet
`n8n/email-pdf-invoices-to-sheet.json` — import in n8n (Workflows → Import from file).

Gmail Trigger (new mail with a PDF attachment and "n8n-invoice" in the subject, so the rest of the inbox is never read) → Extract from File (PDF text) → Code node (same parsing and checks as `core.py`) → Google Sheets append. Every row gets `Status` = OK or CHECK with the reason in `Notes`, so mismatched totals never slip through silently.

Setup: add Gmail and Google Sheets credentials, paste your sheet URL into the last node, create a tab named `Invoices`. Digital (text) PDFs only; scanned PDFs need the OCR path in the Streamlit app. The parsing logic lives in `n8n/parse_invoice.js` and can be tested with Node (`node -e "console.log(require('./n8n/parse_invoice.js').run(text))"`).
