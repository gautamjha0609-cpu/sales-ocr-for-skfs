"""Turn one day's transcription into cell values, checking every number.

The ledger checks itself in several independent ways, and we use all of them:
  * closing - opening = difference;  difference - testing = litres
  * litres x rate = amount;  amount +/- adjustments = boxed amount
  * petrol + diesel + power boxed amounts = total sale (first payment line)
  * all payment lines (udhar, ICICI, Paytm, PhonePe, HP, cash) = total sale
  * udhar list lines = udhar total
A misread digit almost always breaks at least one of these.
"""
import difflib
import re
from dataclasses import dataclass, field
from datetime import date

FUELS = ("petrol", "diesel", "power")


@dataclass
class Day:
    date: date
    sources: list[str]
    rates: dict = field(default_factory=dict)
    nozzles: dict = field(default_factory=lambda: {f: [] for f in FUELS})  # (label, amount)
    readings: list = field(default_factory=list)       # (label, opening, closing) in page order
    payments: dict = field(default_factory=dict)       # cell key -> value
    credit_rows: list = field(default_factory=list)    # dicts: party, fuel, amount, invoice
    credit_all_total: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def fuel_totals(self) -> dict:
        return {f: round(sum(a for _, a in self.nozzles[f]), 2) for f in FUELS}


def _n(v):
    return None if v is None else float(v)


def _fmt(v) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _fuel_by_label(label: str) -> str | None:
    t = re.sub(r"[^a-z]", "", (label or "").lower())
    if t.startswith(("msp", "xp", "power", "pp")):
        return "power"
    if t.startswith(("hsd", "hs", "d")):
        return "diesel"
    if t.startswith(("ms", "p")):
        return "petrol"
    return None


def _fuel_by_rate(rate, rates: dict) -> str | None:
    if rate is None:
        return None
    for f in FUELS:
        if rates.get(f) is not None and abs(rates[f] - rate) < 0.011:
            return f
    return None


class PartyBook:
    def __init__(self, parties: list[dict]):
        self.parties = parties
        self._keys = {self._key(p["name"]): p for p in parties}

    @staticmethod
    def _key(name: str) -> str:
        return re.sub(r"[^a-z]", "", name.lower())

    @property
    def names(self) -> list[str]:
        return [p["name"] for p in self.parties]

    def match(self, name: str) -> dict | None:
        k = self._key(name)
        if not k:
            return None
        if k in self._keys:
            return self._keys[k]
        # "Mool Chand" -> "mool Chand yadav"; "Shyam Transport" -> "Shyam Tran."
        starts = [p for key, p in self._keys.items() if key.startswith(k) or k.startswith(key)]
        if len(starts) == 1 and min(len(k), len(self._key(starts[0]["name"]))) >= 4:
            return starts[0]
        close = difflib.get_close_matches(k, list(self._keys), n=1, cutoff=0.8)
        return self._keys[close[0]] if close else None


def check_nozzle(nz: dict, rates: dict, tol: dict) -> tuple[str | None, float | None, list, list]:
    """Return (fuel, boxed amount, errors, warnings) for one meter block."""
    errs, warns = [], []
    label = nz.get("label") or "?"
    opening, closing = _n(nz.get("opening")), _n(nz.get("closing"))
    diff, testing = _n(nz.get("difference")), _n(nz.get("testing")) or 0.0
    net, rate = _n(nz.get("net_litres")), _n(nz.get("rate"))
    written, final = _n(nz.get("amount_written")), _n(nz.get("final_amount"))
    adjustments = [float(a) for a in nz.get("adjustments") or []]

    if opening is not None and closing is not None:
        calc = round(closing - opening, 2)
        if diff is None:
            diff = calc
        elif abs(calc - diff) > tol["reading"]:
            warns.append(f"{label}: closing {_fmt(closing)} - opening {_fmt(opening)} = "
                         f"{_fmt(calc)}, ledger writes {_fmt(diff)}")
    if diff is not None:
        calc_net = round(diff - testing, 2)
        if net is None:
            net = calc_net
        elif abs(calc_net - net) > tol["reading"]:
            warns.append(f"{label}: {_fmt(diff)} - {_fmt(testing)} = {_fmt(calc_net)}, "
                         f"ledger writes {_fmt(net)} litres")

    fuel_r, fuel_l = _fuel_by_rate(rate, rates), _fuel_by_label(label)
    if rate is not None and fuel_r is None:
        errs.append(f"{label}: rate {_fmt(rate)} matches none of the day's rates")
    fuel = fuel_r or fuel_l
    if fuel_r and fuel_l and fuel_r != fuel_l:
        # trust whichever rate actually reproduces the amount written on the page
        if net is not None and written is not None and rates.get(fuel_l) is not None \
                and abs(net * rates[fuel_l] - written) <= tol["amount"]:
            fuel, rate = fuel_l, rates[fuel_l]
        warns.append(f"{label}: label looks like {fuel_l} but written rate {_fmt(rate if fuel == fuel_r else nz.get('rate'))} "
                     f"is {fuel_r} - amount matches {fuel} rate, counted as {fuel}")
    if fuel is None:
        errs.append(f"{label}: cannot tell if petrol, diesel or power")

    if net is not None and rate is not None and written is not None:
        expected = net * rate
        if abs(expected - written) > tol["amount"]:
            warns.append(f"{label}: {_fmt(net)} x {_fmt(rate)} = {expected:,.2f}, "
                         f"ledger writes {_fmt(written)}")
    if final is None and written is not None:
        final = round(written + sum(adjustments), 2)
    if final is not None and written is not None and adjustments:
        if abs(written + sum(adjustments) - final) > 1:
            warns.append(f"{label}: {_fmt(written)} {' '.join(f'{a:+g}' for a in adjustments)} "
                         f"!= boxed {_fmt(final)}")
    if final is None:
        if net is not None and rate is not None:
            final = round(net * rate, 2)
            warns.append(f"{label}: no boxed amount, using {_fmt(net)} x {_fmt(rate)} = {final:,.2f}")
        else:
            errs.append(f"{label}: no amount found")
    return fuel, final, errs, warns


def merge_extractions(items: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    """Two photos of the same day (e.g. left and right page) -> one extraction."""
    if len(items) == 1:
        return items[0][1], []
    errors = []
    merged = {"rates": {}, "payments": {}, "nozzles": [], "credit_entries": [],
              "other_payments": [], "unclear": [], "sale_total": None,
              "date_text": None, "weekday": None}
    for name, ext in items:
        for group in ("rates", "payments"):
            for k, v in (ext.get(group) or {}).items():
                old = merged[group].get(k)
                if v is not None and old is not None and abs(float(v) - float(old)) > 0.001:
                    errors.append(f"{group}.{k}: {name} says {_fmt(float(v))}, other photo says {_fmt(float(old))}")
                if old is None:
                    merged[group][k] = v
        for k in ("sale_total", "date_text", "weekday"):
            if merged[k] is None:
                merged[k] = ext.get(k)
        for k in ("nozzles", "credit_entries", "other_payments", "unclear"):
            for entry in ext.get(k) or []:
                if entry not in merged[k]:
                    merged[k].append(entry)
    return merged, errors


def build_day(d: date, sources: list[str], ext: dict, cfg: dict, book: PartyBook) -> Day:
    tol = cfg["tolerance"]
    day = Day(date=d, sources=sources)

    # rates -> C4:C6 (if the top box is blank, use the rate the meter blocks multiply by)
    for f in FUELS:
        r = _n((ext.get("rates") or {}).get(f))
        if r is None:
            used = {_n(nz.get("rate")) for nz in ext.get("nozzles") or []
                    if _fuel_by_label(nz.get("label")) == f and nz.get("rate") is not None}
            if len(used) == 1:
                r = used.pop()
                day.warnings.append(f"{f} rate not written at top - using {_fmt(r)} from the meter blocks")
        if r is None:
            day.errors.append(f"{f} rate missing")
        elif not tol["rate_min"] <= r <= tol["rate_max"]:
            day.errors.append(f"{f} rate {_fmt(r)} looks wrong")
        day.rates[f] = r

    # meter blocks -> H/I/J 13..15
    for nz in ext.get("nozzles") or []:
        day.readings.append((nz.get("label") or "?", _n(nz.get("opening")), _n(nz.get("closing"))))
        fuel, amount, errs, warns = check_nozzle(nz, day.rates, tol)
        day.errors += errs
        day.warnings += warns
        if fuel and amount is not None:
            day.nozzles[fuel].append((nz.get("label") or "?", amount))
    if not any(day.nozzles.values()):
        day.errors.append("no meter blocks read")

    sale_total = _n(ext.get("sale_total"))
    fuel_sum = round(sum(day.fuel_totals.values()), 2)
    if sale_total is None:
        day.errors.append("total sale (first line of payment box) missing")
    elif abs(fuel_sum - sale_total) > tol["day_total"]:
        t = day.fuel_totals
        day.errors.append(
            f"petrol {_fmt(t['petrol'])} + diesel {_fmt(t['diesel'])} + power {_fmt(t['power'])} "
            f"= {_fmt(fuel_sum)}, but total sale written is {_fmt(sale_total)}")

    # payment box -> row 8
    p = {k: _n(v) for k, v in (ext.get("payments") or {}).items()}
    zero = lambda *ks: round(sum(p.get(k) or 0.0 for k in ks), 2)
    day.payments = {
        "paytm": zero("paytm_card", "paytm"),
        "hp_card": zero("hp_card"),
        "icici": zero("icici"),
        "phonepe": zero("phonepe_card", "phonepe"),
        "cash": zero("cash"),
        "credit": zero("credit"),
    }
    if p.get("cash") is None:
        day.errors.append("cash line missing")
    others = [(o.get("label"), _n(o.get("amount"))) for o in ext.get("other_payments") or []]
    for label, amt in others:
        if amt:
            day.errors.append(f"payment line {label!r} = {_fmt(amt)} has no column in the sheet")
    paid = round(sum(day.payments.values()) + sum(a or 0 for _, a in others), 2)
    if sale_total is not None and abs(paid - sale_total) > tol["payments"]:
        day.errors.append(f"payment lines add up to {_fmt(paid)}, total sale written is {_fmt(sale_total)}")

    # udhar list -> rows 15..25
    entries = ext.get("credit_entries") or []
    day.credit_all_total = round(sum(float(e["amount"]) for e in entries), 2)
    if abs(day.credit_all_total - day.payments["credit"]) > tol["credit_list"]:
        # common in the ledger (udhar given elsewhere on the page), so a note, not an error
        day.warnings.append(f"udhar lines add up to {_fmt(day.credit_all_total)}, "
                            f"udhar total written is {_fmt(day.payments['credit'])}")
    for e in entries:
        inv = str(e.get("invoice_no") or "").strip()
        inv = re.sub(r"[^\d]", "", inv)
        if not inv:
            continue
        name = (e.get("party_english") or e.get("party") or "").strip()
        known = book.match(name)
        if known is None:
            day.warnings.append(f"new udhar party {name!r} (inv {inv}) - add it to parties.yaml if correct")
        day.credit_rows.append({
            "party": known["name"] if known else name,
            "fuel": e.get("fuel") or (known or {}).get("fuel") or "diesel",
            "amount": round(float(e["amount"]), 2),
            "invoice": int(inv),
        })
    n_rows = cfg["credit_rows"]["last_row"] - cfg["credit_rows"]["first_row"] + 1
    if len(day.credit_rows) > n_rows:
        day.errors.append(f"{len(day.credit_rows)} invoiced udhar lines but the sheet has only {n_rows} rows")

    for note in ext.get("unclear") or []:
        day.warnings.append(f"unclear on photo: {note}")
    return day


def month_checks(days: list[Day]) -> None:
    """Checks across days: meter continuity and duplicate invoice numbers."""
    days = sorted(days, key=lambda d: d.date)
    for prev, day in zip(days, days[1:]):
        if (day.date - prev.date).days != 1 or len(prev.readings) != len(day.readings):
            continue
        for (label, _, closing), (_, opening, _) in zip(prev.readings, day.readings):
            if closing is not None and opening is not None and abs(closing - opening) > 0.001:
                day.warnings.append(f"{label}: opening {_fmt(opening)} but previous day closed at {_fmt(closing)}")
    seen = {}
    for day in days:
        for row in day.credit_rows:
            inv = row["invoice"]
            if inv in seen and seen[inv] != day.date:
                day.warnings.append(f"invoice {inv} also used on {seen[inv]:%d-%m-%Y}")
            seen.setdefault(inv, day.date)
