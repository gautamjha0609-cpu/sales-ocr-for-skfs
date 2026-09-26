# sales-ocr-for-skfs

Turns photos of the handwritten daily sale ledger into the monthly Excel
workbook (one sheet per day, same format and formulas as
`sale Nov-2025.xlsx`), and checks every number before writing it.

## Everyday use (Windows)

1. Put the month's photos in `input\` (or `input\2025-11\`).
   Name each photo with its day: `01.jpeg`, `02.jpeg`, `15.10.jpeg`, `2025-11-30.jpg` all work.
   Two photos of the same day (`07.jpeg`, `07 (2).jpeg`) are combined.
2. Double-click **`run.bat`**.
3. Open `output\sale <Mon>-<Year>.xlsx` and `output\sale <Mon>-<Year> - check report.txt`.

The first run creates a Python environment and installs the packages (needs Python 3.10+).
`rebuild_only.bat` rebuilds the workbook from the saved readings without reading any photo.

## How a photo is read

Each photo is read **once**, and the reading is saved to `data/extracted/<photo>.json`.
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
An ERROR is either a misread digit — fix it in `data/extracted/<photo>.json` and run again — or a
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
| ICICI | L8 (and K17) |
| PhonePe card + PhonePe | N8 |
| cash | R8 |
| udhar total | T8 |
| boxed nozzle amounts (petrol / diesel / power) | H / I / J, rows 13–15 |
| udhar lines with invoice no. | A (party), B (fuel), E (amount), F (invoice), rows 15–25 |
| month udhar register | `Sheet1` |

Q4:Q6, K15, K16, K19 and M20 (cash litres and the Paytm/PhonePe petrol/diesel split) are not in
the ledger photo, so they are left blank for you.

Party names are matched to `parties.yaml` so the same party is always spelled the same.
New parties appear in the report — add them to `parties.yaml`.

## Changing the Excel format

Edit a finished month workbook the way you want, then:

```
python -m skfs_ocr make-template "path\to\your workbook.xlsx"
```

and adjust the cell addresses in `config.yaml` if you moved any input cell.

## Commands

```
python -m skfs_ocr run [--no-api]     read new photos, rebuild workbooks, write report
python -m skfs_ocr pending            list photos not read yet (creates blank JSON)
python -m skfs_ocr tiles <photo>      zoomed crops of a photo, for reading by hand/Claude Code
python -m skfs_ocr fill <photo>       save a compact reading from stdin (see skfs_ocr/fill.py)
python -m skfs_ocr make-template <xlsx>
python -m pytest                      run the tests
```
