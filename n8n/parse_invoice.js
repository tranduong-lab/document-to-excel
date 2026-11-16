// n8n Code node ("Run Once for Each Item"). Input: $json.text from "Extract from File" (PDF).
// Mirrors parse_invoice / check_invoice in core.py.
const MONEY = String.raw`(\d[\d,]*\.\d{2})`;
const num = s => (s == null ? null : parseFloat(s.replace(/,/g, '')));
const grab = (re, t) => { const m = t.match(re); return m ? m[1].trim() : null; };

function parse(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const rec = {
    invoiceNo: grab(/Invoice\s*(?:No|Number|#)\.?:?\s*([A-Z0-9][A-Z0-9-]{3,})/i, text),
    date: grab(/(?:Invoice\s*)?Date:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{4})/i, text),
    vendor: lines.length ? lines[0].replace(/\s*INVOICE$/i, '') : null,
    subtotal: num(grab(new RegExp(String.raw`Subtotal:?\s*\$?` + MONEY, 'i'), text)),
    tax: num(grab(new RegExp(String.raw`^\s*Tax\b.*?:?\s*\$?` + MONEY, 'im'), text)),
    total: num(grab(new RegExp(String.raw`^\s*(?:TOTAL|Amount Due|Total Due):?\s*\$?` + MONEY, 'im'), text)),
  };
  const items = [];
  const lineRe = new RegExp(String.raw`^(.+?)\s+(\S{1,3})\s+\$?` + MONEY + String.raw`\s+\$?` + MONEY + '$');
  for (const l of lines) {
    const m = l.match(lineRe);
    if (m && !/^(subtotal|tax|total)/i.test(l)) {
      items.push({ description: m[1], qty: /^\d+$/.test(m[2]) ? parseInt(m[2]) : null, qtyRead: m[2], unitPrice: num(m[3]), amount: num(m[4]) });
    }
  }
  return { rec, items };
}

function check(rec, items) {
  const issues = [];
  for (const [k, label] of [['invoiceNo', 'Invoice No'], ['date', 'Date'], ['subtotal', 'Subtotal'], ['total', 'Total']])
    if (rec[k] == null) issues.push(`${label}: not readable`);
  if (rec.subtotal != null && items.length) {
    const s = Math.round(items.reduce((a, i) => a + i.amount, 0) * 100) / 100;
    if (Math.abs(s - rec.subtotal) > 0.01) issues.push(`Subtotal: line items add up to ${s.toFixed(2)}`);
  }
  if (rec.subtotal != null && rec.tax != null && rec.total != null && Math.abs(rec.subtotal + rec.tax - rec.total) > 0.01)
    issues.push('Total: subtotal + tax does not equal total');
  for (const i of items) {
    if (i.qty == null) issues.push(`Line items: qty unreadable on '${i.description}'`);
    else if (Math.abs(i.qty * i.unitPrice - i.amount) > 0.01) issues.push(`Line items: '${i.description}' qty x price != amount`);
  }
  return issues;
}

function run(text, meta = {}) {
  const { rec, items } = parse(text || '');
  const issues = check(rec, items);
  return {
    'Received': meta.date || '',
    'From': meta.from || '',
    'File': meta.file || '',
    'Vendor': rec.vendor,
    'Invoice No': rec.invoiceNo,
    'Date': rec.date,
    'Subtotal': rec.subtotal,
    'Tax': rec.tax,
    'Total': rec.total,
    'Line items': items.length,
    'Status': issues.length ? 'CHECK' : 'OK',
    'Notes': issues.join('; '),
  };
}

if (typeof $json !== 'undefined') {
  const src = $('Gmail Trigger').item.json;
  return { json: run($json.text, { date: src.date, from: src.from?.text || src.from, file: $('Gmail Trigger').item.binary?.attachment_0?.fileName || '' }) };
}
if (typeof module !== "undefined") module.exports = { run };
