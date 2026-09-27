"""input photos -> transcriptions -> checked days -> monthly workbook + report."""
import calendar
import json
import os
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

import jsonschema
import yaml

from .dates import chain_dates, guess_month, parse_month_folder, resolve_date
from .extract import (IMAGE_EXTS, ClaudeReader, ExtractionError, blank_extraction,
                      save_record, sha256)
from .schema import EXTRACTION_SCHEMA
from .validate import Day, PartyBook, build_day, merge_extractions, month_checks
from .workbook import month_dir, output_path, write_month


def load_parties(cfg: dict) -> PartyBook:
    path = cfg["paths"]["parties"]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return PartyBook((data or {}).get("parties") or [])


def _photos(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def discover(cfg: dict) -> list[Path]:
    """New photos in input/ plus already-filed photos in raw_data/ (so a month
    is always rebuilt from all of its days)."""
    return _photos(cfg["paths"]["input"]) + _photos(cfg["paths"]["raw"])


def in_input(cfg: dict, photo: Path) -> bool:
    return photo.is_relative_to(cfg["paths"]["input"])


def cache_file(cfg: dict, photo: Path) -> Path:
    """input/03.jpeg -> data/extracted/03.jpeg.json
    raw_data/FY2025-26/07 Oct-2025/03.jpeg -> data/extracted/FY2025-26/07 Oct-2025/03.jpeg.json"""
    root = cfg["paths"]["input"] if in_input(cfg, photo) else cfg["paths"]["raw"]
    rel = photo.relative_to(root)
    return cfg["paths"]["extracted"] / rel.parent / f"{rel.name}.json"


def input_photos(cfg: dict) -> list[Path]:
    """Photos in input/, numbered #1, #2 ... in this order (stable while filling)."""
    return _photos(cfg["paths"]["input"])


def find_photo(cfg: dict, name: str) -> Path | None:
    """Accepts '#3' (number from `pending`), a file name, or a path."""
    if name.startswith("#") and name[1:].isdigit():
        photos = input_photos(cfg)
        i = int(name[1:]) - 1
        return photos[i] if 0 <= i < len(photos) else None
    p = Path(name)
    if p.exists():
        return p.resolve()
    for photo in discover(cfg):
        if photo.name == name or str(photo).endswith(name):
            return photo
    return None


def archive(cfg: dict, photo: Path, day: date, log) -> Path:
    """Move a photo from input/ to raw_data/FY.../MM Mon-YYYY/<yyyy-mm-dd>.jpg with its
    reading. The date in the file name means it never has to be worked out again."""
    dest_dir = cfg["paths"]["raw"] / month_dir(cfg, day.year, day.month)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_json = cache_file(cfg, photo)
    dest = dest_dir / f"{day:%Y-%m-%d}{photo.suffix.lower()}"
    if dest.exists() and sha256(dest) != sha256(photo):
        n = 2
        while (dest_dir / f"{day:%Y-%m-%d} ({n}){photo.suffix.lower()}").exists():
            n += 1
        dest = dest_dir / f"{day:%Y-%m-%d} ({n}){photo.suffix.lower()}"
    if dest.exists() and sha256(dest) == sha256(photo):     # same photo put in twice
        photo.unlink()
        src_json.unlink(missing_ok=True)
        return dest
    shutil.move(str(photo), dest)
    dest_json = cache_file(cfg, dest)
    dest_json.parent.mkdir(parents=True, exist_ok=True)
    if src_json.exists():
        record = json.loads(src_json.read_text(encoding="utf-8"))
        record["source"] = dest.name
        dest_json.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        src_json.unlink()
    return dest


def clean_empty_dirs(root: Path) -> None:
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()


def load_record(cfg: dict, photo: Path) -> tuple[dict | None, str]:
    """(record, status) where status is ok / missing / changed / invalid: <why>."""
    f = cache_file(cfg, photo)
    if not f.exists():
        return None, "missing"
    try:
        record = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"invalid: {f.name} is not valid JSON ({e})"
    digest = sha256(photo)
    if record.get("sha256") not in (None, digest):
        return None, "changed"
    if not record.get("read_by"):
        return None, "missing"
    try:
        jsonschema.validate(record["extraction"], EXTRACTION_SCHEMA)
    except (KeyError, jsonschema.ValidationError) as e:
        where = "/".join(map(str, getattr(e, "absolute_path", []))) or "extraction"
        return None, f"invalid: {f.name} at {where}: {getattr(e, 'message', e)}"
    return record, "ok"


def write_stub(cfg: dict, photo: Path) -> Path:
    """Blank JSON for a photo, to be filled by Claude Code or by hand."""
    f = cache_file(cfg, photo)
    save_record(f, {"source": photo.name, "sha256": sha256(photo), "read_by": None,
                    "extraction": blank_extraction()})
    return f


def read_with_api(cfg: dict, photos: list[Path], book: PartyBook, log) -> None:
    reader = ClaudeReader(cfg, book.names)
    for photo in photos:
        log(f"  reading {photo.name} with {cfg['claude']['model']} ...")
        try:
            ext = reader.read(photo)
            for _ in range(cfg["claude"]["retry_on_errors"]):
                problems = build_day(date.today(), [photo.name], ext, cfg, book).errors
                if not problems:
                    break
                log(f"    {len(problems)} check(s) failed, looking again")
                ext = reader.reread(ext, problems)
        except ExtractionError as e:
            log(f"    FAILED: {e}")
            continue
        save_record(cache_file(cfg, photo), {
            "source": photo.name, "sha256": sha256(photo),
            "read_by": cfg["claude"]["model"], "extraction": ext})
    log(f"  tokens used: {reader.usage['input_tokens']:,} in / {reader.usage['output_tokens']:,} out")


def run(cfg: dict, use_api: bool | None = None, log=print) -> int:
    book = load_parties(cfg)
    photos = discover(cfg)
    if not photos:
        log(f"No photos found in {cfg['paths']['input']} or {cfg['paths']['raw']}")
        return 1
    if not _photos(cfg["paths"]["input"]):
        log("input/ is empty - rebuilding workbooks from raw_data/")
    filed = {sha256(p): p for p in _photos(cfg["paths"]["raw"])}
    for p in _photos(cfg["paths"]["input"]):
        if sha256(p) in filed:                      # already filed earlier: drop the copy
            log(f"{p.name} is already filed as {filed[sha256(p)].relative_to(cfg['paths']['raw'])} - removed from input/")
            p.unlink()
            cache_file(cfg, p).unlink(missing_ok=True)
            photos.remove(p)

    status = {p: load_record(cfg, p) for p in photos}
    todo = [p for p, (_, s) in status.items() if s in ("missing", "changed")]
    if todo:
        if use_api is None:
            use_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if use_api:
            log(f"{len(todo)} new photo(s) to read:")
            read_with_api(cfg, todo, book, log)
            status.update({p: load_record(cfg, p) for p in todo})
        else:
            for p in todo:
                if status[p][1] == "changed" or not cache_file(cfg, p).exists():
                    write_stub(cfg, p)

    problems_global = []
    unread = []
    for p, (rec, s) in status.items():
        if rec is None:
            unread.append(p)
            problems_global.append(f"{p.name}: " + ("not read yet" if s in ("missing", "changed") else s))

    # group readable photos by month
    by_month: dict[tuple[int, int], list] = defaultdict(list)
    loose = []
    for p, (rec, _) in status.items():
        if rec is None:
            continue
        folder = parse_month_folder(p.parent.name)
        (by_month[folder] if folder else loose).append((p, rec["extraction"]))
    if loose:
        # each loose photo goes to the month of its own full date; photos that
        # only give a day number ("03.jpg", page "3") follow the majority month
        fallback = guess_month([(p.stem, e) for p, e in loose])
        for p, ext in loose:
            own = guess_month([(p.stem, ext)]) or fallback
            if own is None:
                problems_global.append(f"{p.name}: cannot tell the month - put it in input/YYYY-MM/ (e.g. input/2025-11/)")
            else:
                by_month[own].append((p, ext))

    exit_code = 0
    moved = 0
    for (year, month), items in sorted(by_month.items()):
        n_err, placed = build_month(cfg, book, year, month, items, unread, log)
        exit_code |= int(n_err > 0)
        if cfg["workbook"].get("archive_input", True):
            for photo, day in placed:
                if in_input(cfg, photo):
                    archive(cfg, photo, day, log)
                    moved += 1
    if moved:
        clean_empty_dirs(cfg["paths"]["input"])
        clean_empty_dirs(cfg["paths"]["extracted"])
        log(f"\n{moved} photo(s) moved from input/ to {cfg['paths']['raw'].name}/ (input is ready for the next run)")
    if problems_global:
        exit_code = 1
        log("\nPhotos not in any workbook yet:")
        for msg in problems_global:
            log(f"  - {msg}")
        if any("not read yet" in m for m in problems_global):
            log("  -> set ANTHROPIC_API_KEY and run again, or ask Claude Code to "
                "'read the new ledger photos' (see README).")
    return exit_code


def build_month(cfg, book, year, month, items, unread, log) -> tuple[int, list]:
    """Write the month's workbook and report; return (errors, photos placed in the workbook)."""
    per_date: dict[date, list] = defaultdict(list)
    placed: list = []                   # (photo, date)
    date_errors = []
    date_warn: dict[date, list] = defaultdict(list)
    resolved = []
    for photo, ext in items:
        d, errs, warns = resolve_date(photo.stem, ext, year, month)
        resolved.append((photo, ext, d, errs, warns))
    # meter chain fills missing dates and corrects misread ones
    chained, chain_notes = chain_dates([(p.name, e, d) for p, e, d, _, _ in resolved])
    notes_by_photo = defaultdict(list)
    for note in chain_notes:
        notes_by_photo[note.split(": ", 1)[0]].append(note.split(": ", 1)[1])
    for (photo, ext, _, errs, warns), d in zip(resolved, chained):
        if d is None:
            date_errors += [f"{photo.name}: {e}" for e in errs]
            continue
        if (d.year, d.month) != (year, month):
            date_errors.append(f"{photo.name}: date {d:%d-%m-%Y} is outside {year}-{month:02d}")
            continue
        per_date[d].append((photo.name, ext))
        placed.append((photo, d))
        date_warn[d] += notes_by_photo[photo.name] + [w for w in warns if not notes_by_photo[photo.name]]

    days: list[Day] = []
    for d, group in sorted(per_date.items()):
        ext, merge_errors = merge_extractions(group)
        day = build_day(d, [n for n, _ in group], ext, cfg, book)
        day.errors = merge_errors + day.errors
        day.warnings = date_warn[d] + day.warnings
        if len(group) > 1:
            day.warnings.insert(0, f"{len(group)} photos combined: {', '.join(n for n, _ in group)}")
        days.append(day)
    month_checks(days)

    out = write_month(cfg, days, year, month) if days else None
    report = report_path(cfg, year, month)
    n_err = write_report(report, year, month, days, date_errors)
    shown = out.relative_to(cfg["paths"]["output"].parent) if out else "no workbook"
    log(f"\n{calendar.month_name[month]} {year}: {len(days)} day sheet(s) -> {shown}")
    ok = sum(1 for d in days if not d.errors and not d.warnings)
    log(f"  {ok} clean, {sum(1 for d in days if d.warnings and not d.errors)} with notes, "
        f"{sum(1 for d in days if d.errors)} with ERRORS  (details: {report.name})")
    for d in days:
        for e in d.errors:
            log(f"  ERROR {d.date:%d-%m}: {e}")
    for e in date_errors:
        log(f"  ERROR {e}")
    return n_err, placed if out else []


def report_path(cfg: dict, year: int, month: int) -> Path:
    wb = output_path(cfg, year, month)
    return wb.with_name(wb.stem + " - check report.txt")


def write_report(path: Path, year: int, month: int, days: list[Day], date_errors: list[str]) -> int:
    got = {d.date.day for d in days}
    missing = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if d not in got]
    lines = [f"Check report - {calendar.month_name[month]} {year}", ""]
    if missing:
        lines.append("No photo for day(s): " + ", ".join(map(str, missing)))
    lines += [f"ERROR {e}" for e in date_errors]
    n_err = len(date_errors)
    for d in days:
        state = "ERROR" if d.errors else ("CHECK" if d.warnings else "OK")
        t = d.fuel_totals
        lines += ["", f"{d.date:%d-%m-%Y}  [{state}]  photo: {', '.join(d.sources)}",
                  f"   petrol {t['petrol']:,.2f} | diesel {t['diesel']:,.2f} | power {t['power']:,.2f}"
                  f" | udhar lines with invoice: {len(d.credit_rows)}"]
        lines += [f"   ERROR: {e}" for e in d.errors]
        lines += [f"   note:  {w}" for w in d.warnings]
        n_err += len(d.errors)
    lines += ["", "How to fix: open data/extracted/<photo>.json, correct the number, run again.",
              "If the ledger itself has the mistake, the ERROR is real - fix it in Excel."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n_err
