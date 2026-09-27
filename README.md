# sales-ocr-for-skfs

Turns photos of the handwritten daily sale ledger into the monthly Excel
workbook (one sheet per day, same format and formulas as
`template/sample sale Oct-2025.xlsx`), and checks every number before writing it.

## Everyday use (Windows)

1. Put the new photos in `input\` (any month, any number of photos).
   Name each photo with its day: `01.jpeg`, `02.jpeg`, `15.10.jpeg`, `2025-11-30.jpg` all work.
   Two photos of the same day (`07.jpeg`, `07 (2).jpeg`) are combined.
2. Double-click **`run.bat`**.
3. Open the workbook and check report in `output\FY2025-26\07 Oct-2025\`.

After the run, every photo that went into a workbook is **moved out of `input\`** into
`raw_data\`, so `input\` is empty and ready for the next batch. Photos that could not be
used yet (not read, no date) stay in `input\` and are listed at the end of the run.

`rebuild_only.bat` rebuilds the workbooks from the saved readings without reading any photo.

## Folders (financial year April–March)

```
input/                                   new photos only (empty after a run)
raw_data/FY2025-26/01 Apr-2025/ ...      every photo, filed by FY and month
raw_data/FY2025-26/07 Oct-2025/01.10.jpeg
raw_data/FY2025-26/12 Mar-2026/
raw_data/FY2026-27/01 Apr-2026/
output/FY2025-26/07 Oct-2025/sale Oct-2025.xlsx
output/FY2025-26/07 Oct-2025/sale Oct-2025 - check report.txt
data/extracted/FY2025-26/07 Oct-2025/01.10.jpeg.json   what was read from each photo
```

Months are numbered in FY order (01 = April … 12 = March). Each run rebuilds a month from
all of its photos in `raw_data` plus the new ones, so adding day 15 later keeps days 1–14.
Folder names are set in `config.yaml` (`fy_folder`, `month_folder`).

## How a photo is read

Each photo is read **once**, and the reading is saved as a JSON file in `data/extracted/` (same FY/month folders).
After that, running again never re-reads it (zero tokens), unless the photo file changes.

* **With an API key** (`set ANTHROPIC_API_KEY=...` before `run.bat`): new photos are
  sent to Claude (`claude.model` in `config.yaml`). If the numbers don't add up, the
  photo is looked at once more with the failed checks listed.
* **Without an API key**: `run.bat` creates blank JSON files for new photos. Open
  Claude Code in this folder and say *"read the new ledger photos"*; it follows
  `CLAUDE.md`, fills the JSON files, and rebuilds the workbook.

Handwriting OCR engines (Tesseract, EasyOCR, PaddleOCR) were tried in design and left out:
they cannot reliably read Hindi/English handwritten digits on ruled paper, and a
misread digit is worse than none. Claude reads the photo; Python does all the maths.

## What is checked (nothing is written silently)

| Check | Where the numbers come from |
|---|---|
| closing − opening = difference, difference − testing = litres | each meter block |
| litres × rate = amount, amount ± adjustments = boxed amount | each meter block |
| petrol + diesel + power = total sale | meter blocks vs first line of payment box |
| udhar + ICICI + Paytm + PhonePe + HP + cash = total sale | payment box |
| udhar lines = udhar total | udhar list |
| today's opening = yesterday's closing | consecutive days |
| rates, weekday, file-name date vs page date, duplicate invoice numbers | |

The report marks each day **OK**, **CHECK** (a note to look at), or **ERROR** (numbers don't add up).
An ERROR is either a misread digit — fix it in the photo's JSON under `data/extracted/` and run again (`rebuild_only.bat`) — or a
real mistake in the ledger itself, which you then correct in Excel. The workbook's own
"sales value diff" cell (D11) shows the same difference.

After saving, the workbook is re-opened and every written cell is compared with what should be
there; the file is only replaced if that check passes (and never while it is open in Excel).

## What goes where in the sheet

Only input cells are written; every formula from your workbook is kept. All addresses are in
`config.yaml`:

| Ledger | Cell |
|---|---|
| petrol / diesel / power rate | C4 / C5 / C6 |
| Paytm card + Paytm | H8 |
| HP card | J8 |
| ICICI | L8 |
| PhonePe card + PhonePe | N8 |
| cash | R8 |
| udhar total | T8 |
| boxed nozzle amounts (petrol / diesel / power) | H / I / J, rows 13–15 |
| udhar lines with invoice no. | A (party), B (fuel), E (amount), F (invoice), rows 15–25 |
| cash qty petrol / diesel / power | Q4 / Q5 / Q6 (worked out, see below) |

Qty, the Paytm/PhonePe 60/40 petrol/diesel split, ICICI and HP litres are formulas in the
template. Cash qty (Q4:Q6) is written as a number, worked out the same way as in the October
workbook: sale qty − Paytm share − ICICI − PhonePe share − HP card − udhar qty, so the
"Qty Diffrence" column comes to 0.

Party names are matched to `parties.yaml` so the same party is always spelled the same.
New parties appear in the report — add them to `parties.yaml`.

## Changing the Excel format

Edit a finished month workbook the way you want, then:

```
python -m skfs_ocr make-template "path\to\your workbook.xlsx"
```

(the current template was made from `template/sample sale Oct-2025.xlsx`)

```
```

and adjust the cell addresses in `config.yaml` if you moved any input cell.

## Commands

```
python -m skfs_ocr run [--no-api]     read new photos, rebuild workbooks, report, move photos to raw_data
python -m skfs_ocr pending            list photos not read yet (creates blank JSON)
python -m skfs_ocr tiles '#n' | --pending   zoomed crops (numbers from `pending`)
python -m skfs_ocr fill '#n'          save a compact reading from stdin (see skfs_ocr/fill.py)
python -m skfs_ocr make-template <xlsx>
python -m pytest                      run the tests
```
