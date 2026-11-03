"""Custom-field extraction with Claude. Every value must come with an exact quote from the
document; quotes that cannot be found in the text are flagged instead of trusted."""
import re

from core import Page, Result

TOOL = {
    "name": "record_fields",
    "description": "Record the requested fields found in the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": ["string", "null"]},
                        "quote": {"type": ["string", "null"],
                                  "description": "Exact text copied from the document that contains the value"},
                    },
                    "required": ["name", "value", "quote"],
                },
            }
        },
        "required": ["fields"],
    },
}

PROMPT = """Extract these fields from the document page below: {fields}.
Rules:
- Copy each value exactly as written. Do not calculate, convert or infer.
- "quote" must be copied character for character from the document and contain the value.
- If a field is missing or unreadable, set value and quote to null.

<document>
{text}
</document>"""


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify(fields, text):
    doc = _norm(text)
    out = {}
    for f in fields:
        v, q = f.get("value"), f.get("quote")
        if v in (None, ""):
            out[f["name"]] = (None, "not found in document")
        elif not q or _norm(q) not in doc:
            out[f["name"]] = (v, "quote not found in document - please confirm")
        elif _norm(v) not in _norm(q):
            out[f["name"]] = (v, "value not inside its quote - please confirm")
        else:
            out[f["name"]] = (v, None)
    return out


def extract_fields(pages: list[Page], field_names: list[str], api_key: str, model: str, client=None) -> Result:
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    cols = ["Page"] + field_names + ["Status", "Notes", "Read by"]
    rows, flags, evidence = [], [], []
    for p in pages:
        msg = client.messages.create(
            model=model, max_tokens=2000, tools=[TOOL], tool_choice={"type": "tool", "name": "record_fields"},
            messages=[{"role": "user", "content": PROMPT.format(fields=", ".join(field_names), text=p.text)}])
        fields = next(b.input for b in msg.content if b.type == "tool_use")["fields"]
        checked = verify(fields, p.text)
        issues = {n: checked.get(n, (None, "not returned"))[1] for n in field_names}
        issues = {k: v for k, v in issues.items() if v}
        rows.append([p.number] + [checked.get(n, (None,))[0] for n in field_names]
                    + ["CHECK" if issues else "OK", "; ".join(f"{k}: {v}" for k, v in issues.items()), p.method])
        flags.append(set(issues))
        evidence += [[p.number, f["name"], f.get("value"), f.get("quote")] for f in fields]
    flagged = sum(1 for r in rows if r[-3] == "CHECK")
    summary = [("Pages processed", len(pages)), ("Pages OK", len(rows) - flagged), ("Pages to confirm", flagged),
               ("Fields requested", ", ".join(field_names)),
               ("Rule", "Each value is backed by an exact quote from the page; anything unverified is highlighted")]
    return Result(cols, rows, flags, [], {"Evidence": (["Page", "Field", "Value", "Quote from document"], evidence, None)},
                  summary)
