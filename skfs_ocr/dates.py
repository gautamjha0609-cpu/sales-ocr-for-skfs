"""Work out which day a ledger photo belongs to.

Priority: date in the file name (30.jpg, 30.10.jpg, 2025-10-30.jpg), then
the date written on the page ("30/10/25"). A month folder (input/2025-10/)
or the page dates of the other photos fill in a missing month/year.
"""
import re
from collections import Counter
from datetime import date

from .schema import WEEKDAYS

_YMD = re.compile(r"(?<!\d)(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)")
_DMY = re.compile(r"(?<!\d)(\d{1,2})\s*[-_./|\\ ]\s*(\d{1,2})(?:\s*[-_./|\\ ]\s*(\d{2,4}))?(?!\d)")
# file names: "30", "30.10", "30-10-2025", "30 (2)", "30a", "day 30"
_NAME = re.compile(
    r"^(?:day)?[\s_-]*(\d{1,2})(?:[-_.](\d{1,2})(?:[-_.](\d{2,4}))?)?"
    r"(?:[\s_-]*\(\d+\)|[\s_-]*[a-z])?$", re.I)


MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse_month_folder(name: str) -> tuple[int, int] | None:
    """"2025-10" (input) or "07 Oct-2025" (raw_data / output) -> (2025, 10)."""
    m = re.fullmatch(r"(20\d{2})[-_](\d{1,2})", name)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"([A-Za-z]{3})[a-z]*[-_ ](20\d{2})$", name)
    if m and m.group(1).lower() in MONTH_ABBR:
        return int(m.group(2)), MONTH_ABBR.index(m.group(1).lower()) + 1
    return None


def fy_of(year: int, month: int) -> int:
    """Financial year (April-March) start year: Oct-2025 -> 2025, Feb-2026 -> 2025."""
    return year if month >= 4 else year - 1


def _year(y: str | None, default: int | None) -> int | None:
    if y is None:
        return default
    return int(y) + 2000 if len(y) == 2 else int(y)


def _make(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def parse_page_date(text: str | None, year: int | None, month: int | None) -> date | None:
    if not text:
        return None
    m = _YMD.search(text)
    if m:
        return _make(*m.groups())
    m = _DMY.search(text)
    if m:
        return _make(_year(m.group(3), year), m.group(2), m.group(1))
    m = re.fullmatch(r"\s*(\d{1,2})\s*", text)
    if m:
        return _make(year, month, m.group(1))
    return None


def parse_file_date(stem: str, year: int | None, month: int | None) -> date | None:
    """Only names that ARE a date count. Camera/WhatsApp names such as
    "WhatsApp Image 2025-05-15 at 21.53.51" carry the sending date, not the
    ledger date, so they are ignored and the date written on the page is used."""
    stem = stem.strip()
    m = re.fullmatch(r"(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})(?:[\s_-]*\(\d+\)|[\s_-]*[a-z])?", stem, re.I)
    if m:
        return _make(*m.groups())
    m = _NAME.match(stem.strip())
    if not m:
        return None
    d, mo, y = m.groups()
    return _make(_year(y, year), mo or month, d)


def guess_month(items: list[tuple[str, dict]]) -> tuple[int, int] | None:
    """Most common (year, month) from page dates / file names of a batch."""
    votes = Counter()
    for stem, ext in items:
        for dt in (parse_page_date(ext.get("date_text"), None, None),
                   parse_file_date(stem, None, None)):
            if dt:
                votes[(dt.year, dt.month)] += 1
    return votes.most_common(1)[0][0] if votes else None


def resolve_date(stem: str, extraction: dict, year: int, month: int) -> tuple[date | None, list[str], list[str]]:
    """Return (date, errors, warnings)."""
    errors, warnings = [], []
    from_name = parse_file_date(stem, year, month)
    from_page = parse_page_date(extraction.get("date_text"), year, month)
    chosen = from_name or from_page
    if chosen is None:
        errors.append(f"no date: page says {extraction.get('date_text')!r} - "
                      f"rename the photo to the day number, e.g. 07.jpg")
        return None, errors, warnings
    if from_name and from_page and from_name != from_page:
        warnings.append(f"file name gives {from_name:%d-%m-%Y} but page says "
                        f"{extraction.get('date_text')!r} - using file name")
    weekday = extraction.get("weekday")
    if weekday in WEEKDAYS and WEEKDAYS[chosen.weekday()] != weekday:
        warnings.append(f"page weekday {weekday} does not match {chosen:%d-%m-%Y} "
                        f"({WEEKDAYS[chosen.weekday()]})")
    return chosen, errors, warnings


# ---- dating pages by meter readings -----------------------------------------

def _readings(ext: dict) -> tuple[set, set]:
    op, cl = set(), set()
    for nz in ext.get("nozzles") or []:
        if nz.get("opening") is not None:
            op.add(round(float(nz["opening"]), 2))
        if nz.get("closing") is not None:
            cl.add(round(float(nz["closing"]), 2))
    return op, cl


def follows(prev: dict, nxt: dict, min_match: int = 3) -> bool:
    """True if `nxt` opens where `prev` closed (at least `min_match` meters agree)."""
    return len(_readings(prev)[1] & _readings(nxt)[0]) >= min_match


def chain_dates(items: list[tuple[str, dict, date | None]]) -> tuple[list[date | None], list[str]]:
    """Fix or fill dates using the meter chain: every day opens where the day
    before closed. Pages are linked into runs; each run takes the date offset
    most of its dated pages agree on. So a smudged or missing date (WhatsApp
    file names, "?/4/25") gets the right day, and a misread date is corrected.

    items: (name, extraction, date from file name / page or None)
    returns: (dates, notes)"""
    n = len(items)
    nxt = [None] * n
    prv = [None] * n
    for i in range(n):
        for j in range(n):
            if i != j and nxt[i] is None and prv[j] is None and follows(items[i][1], items[j][1]):
                nxt[i], prv[j] = j, i
    dates = [d for _, _, d in items]
    notes = []
    seen = set()
    for start in range(n):
        if prv[start] is not None or start in seen:
            continue
        run, k = [], start
        while k is not None and k not in seen:
            seen.add(k)
            run.append(k)
            k = nxt[k]
        votes = Counter(dates[k].toordinal() - pos for pos, k in enumerate(run) if dates[k])
        if not votes or len(run) == 1:
            continue
        offset = votes.most_common(1)[0][0]
        for pos, k in enumerate(run):
            chained = date.fromordinal(offset + pos)
            if dates[k] is None:
                notes.append(f"{items[k][0]}: no readable date - dated {chained:%d-%m-%Y} by meter readings")
            elif dates[k] != chained:
                notes.append(f"{items[k][0]}: page/file says {dates[k]:%d-%m-%Y} but meter readings "
                             f"give {chained:%d-%m-%Y} - using meter readings")
            dates[k] = chained
    return dates, notes
