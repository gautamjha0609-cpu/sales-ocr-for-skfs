"""Build template/template.xlsx from one of your finished month workbooks.

Keeps every formula, label, format and column width of the chosen day
sheet; only blanks the cells that change from day to day so no old value
can leak into a new day. Run once (or again if you change the format):

    python -m skfs_ocr make-template "template/sample sale Oct-2025.xlsx"
"""
from pathlib import Path

import openpyxl


def day_input_cells(cfg: dict) -> list[str]:
    """Every cell the program writes (or blanks) on a day sheet."""
    c = cfg["cells"]
    cells = [c[k] for k in ("rate_petrol", "rate_diesel", "rate_power", "paytm", "hp_card",
                            "icici", "phonepe", "cash", "credit")]
    cells += list(cfg.get("cash_qty", {}).values())
    for col in (c["petrol_col"], c["diesel_col"], c["power_col"]):
        cells += [f"{col}{r}" for r in c["nozzle_rows"]]
    cr = cfg["credit_rows"]
    for r in range(cr["first_row"], cr["last_row"] + 1):
        cells += [f"{cr[k]}{r}" for k in ("party_col", "amount_col", "invoice_col")]
    return cells + list(cfg["manual_cells"])


def make_template(cfg: dict, sample: Path, sheet: str | None = None) -> Path:
    wb = openpyxl.load_workbook(sample)
    day = wb[sheet] if sheet else wb.worksheets[0]
    reg_name = cfg["workbook"]["register_sheet"]
    keep = {day.title} | ({reg_name} if reg_name and reg_name in wb.sheetnames else set())
    for ws in list(wb.worksheets):
        if ws.title not in keep:
            wb.remove(ws)
    day.title = cfg["workbook"]["template_day_sheet"]

    for ref in day_input_cells(cfg):
        if not str(day[ref].value or "").startswith("="):
            day[ref].value = None
    cr = cfg["credit_rows"]
    for r in range(cr["first_row"], cr["last_row"] + 1):
        day[f"{cr['type_col']}{r}"].value = cr["default_type"]
        # rate always follows the day's rate for the row's fuel type
        day[f"{cr['rate_col']}{r}"].value = f"=+VLOOKUP({cr['type_col']}{r},A$4:C$6,3,0)"
    # sample had a pasted number here; every other total on the row is a SUM
    q = day["Q7"]
    if not str(q.value or "").startswith("="):
        q.value = "=SUM(Q4:Q6)"

    if reg_name and reg_name in wb.sheetnames:
        reg = wb[reg_name]
        first = cfg["workbook"]["register_first_row"]
        if reg.max_row >= first:
            reg.delete_rows(first, reg.max_row - first + 1)

    out = cfg["paths"]["template"]
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out

