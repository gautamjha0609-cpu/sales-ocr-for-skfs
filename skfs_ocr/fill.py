"""Save a transcription typed in compact form (used by Claude Code, saves tokens).

    python -m skfs_ocr fill 03.jpeg < day.json

Compact JSON keys:
  d  date as written ("3/10/25")          r  [petrol, diesel, power] rates
  n  meter blocks: [label, opening, closing, difference, testing, net_litres,
                    rate, amount_written, [adjustments], final_amount]
  t  total sale (first payment line)
  p  [udhar, icici, paytm_card, paytm, phonepe_card, phonepe, hp_card, cash]
  c  udhar lines: [amount, party as written, party in English, invoice or null, fuel or null]
  o  other payment lines: [label, amount]      u  notes on unclear digits
"""
from datetime import date
from pathlib import Path

from .extract import save_record, sha256
from .schema import PAYMENT_KEYS

NOZZLE_KEYS = ["label", "opening", "closing", "difference", "testing", "net_litres",
               "rate", "amount_written", "adjustments", "final_amount"]


def expand(c: dict) -> dict:
    return {
        "date_text": c["d"],
        "weekday": c.get("w"),
        "rates": dict(zip(["petrol", "diesel", "power"], c["r"])),
        "nozzles": [dict(zip(NOZZLE_KEYS, n)) for n in c["n"]],
        "sale_total": c["t"],
        "payments": dict(zip(PAYMENT_KEYS, c["p"])),
        "other_payments": [{"label": a, "amount": b} for a, b in c.get("o", [])],
        "credit_entries": [dict(zip(["amount", "party", "party_english", "invoice_no", "fuel"], e))
                           for e in c["c"]],
        "unclear": c.get("u", []),
    }


def fill(cfg: dict, photo: Path, compact: dict) -> list[str]:
    from .pipeline import cache_file, load_parties
    from .validate import build_day

    ext = expand(compact)
    save_record(cache_file(cfg, photo), {"source": photo.name, "sha256": sha256(photo),
                                         "read_by": "claude-code", "extraction": ext})
    day = build_day(date.today(), [photo.name], ext, cfg, load_parties(cfg))
    t = day.fuel_totals
    lines = [f"petrol {t['petrol']:,.2f} + diesel {t['diesel']:,.2f} + power {t['power']:,.2f}"
             f" = {sum(t.values()):,.2f}   total written {ext['sale_total']}"]
    lines += [f"ERROR {e}" for e in day.errors] + [f"note  {w}" for w in day.warnings]
    return lines
