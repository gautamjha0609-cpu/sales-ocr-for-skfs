"""What we ask Claude to read from one ledger photo.

Claude only transcribes. All arithmetic (sums, checks, fuel classification)
is done in Python by validate.py, so a single misread digit shows up as a
failed check instead of silently landing in the workbook.
"""

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

PAYMENT_KEYS = [
    "credit",        # उधार
    "icici",
    "paytm_card",
    "paytm",
    "phonepe_card",
    "phonepe",
    "hp_card",
    "cash",
]


def _num():
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _str():
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


NOZZLE = _obj({
    "label": {"type": "string"},
    "opening": _num(),
    "closing": _num(),
    "difference": _num(),
    "testing": _num(),
    "net_litres": _num(),
    "rate": _num(),
    "amount_written": _num(),
    "adjustments": {"type": "array", "items": {"type": "number"}},
    "final_amount": _num(),
})

CREDIT_ENTRY = _obj({
    "amount": {"type": "number"},
    "party": {"type": "string"},
    "party_english": {"type": "string"},
    "invoice_no": _str(),
    "fuel": {"anyOf": [{"type": "string", "enum": ["diesel", "petrol", "power"]}, {"type": "null"}]},
})

EXTRACTION_SCHEMA = _obj({
    "date_text": _str(),
    "weekday": {"anyOf": [{"type": "string", "enum": WEEKDAYS}, {"type": "null"}]},
    "rates": _obj({"petrol": _num(), "diesel": _num(), "power": _num()}),
    "nozzles": {"type": "array", "items": NOZZLE},
    "sale_total": _num(),
    "payments": _obj({k: _num() for k in PAYMENT_KEYS}),
    "other_payments": {
        "type": "array",
        "items": _obj({"label": {"type": "string"}, "amount": _num()}),
    },
    "credit_entries": {"type": "array", "items": CREDIT_ENTRY},
    "unclear": {"type": "array", "items": {"type": "string"}},
})

PROMPT = """Transcribe this handwritten petrol-pump daily ledger (Hindi/English, two-page spread). Copy digits exactly as written; never compute, round or correct. Use null for blank, "-", "~" or dash entries.

- date_text: the date at top-left, as written (e.g. "30/11/25"). weekday: only if a weekday word is written.
- rates: box at top centre. "ms"=petrol, "HSD"=diesel, "msp"/power=power petrol.
- nozzles: left page has meter blocks (label like MS-1, HSD-2, MSP-1). Each block: opening reading, closing reading, difference, testing (written "-5" -> 5), "litres x rate", amount_written, any further +/- adjustment lines (e.g. "-6" -> -6), and final_amount = the boxed/underlined figure. Include every block. Ignore the stock lines at the very top of the page.
- sale_total: first line of the payment box (the day's total sale, e.g. "इस्टोमा/टोटल - 214004").
- payments: lines in that box: उधार->credit, ICICI, Paytm card, Paytm, PhonePe card, PhonePe, HP card, Cash. Any other line -> other_payments.
- credit_entries: the उधार list at bottom right. Each line: amount at start, party name, invoice number in brackets at end (null if none). party = name as written; party_english = romanised name, using the spelling from this list when it is the same party: {parties}. fuel only if the line marks it (e.g. "P"/petrol), else null.
- unclear: short notes on any digit you are not sure of (e.g. "paytm 27779.36 vs 27777.36").
"""

RETRY_PROMPT = """Your previous transcription (below) fails these arithmetic checks:
{problems}

Look at the photo again, re-read ONLY the digits involved, and return the full corrected JSON. Keep the original handwriting values - if the ledger itself is wrong, keep what is written.

Previous transcription:
{previous}
"""
