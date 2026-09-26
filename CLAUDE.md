# Reading new ledger photos (no API key)

When asked to "read the new ledger photos" (or similar):

1. `python -m skfs_ocr pending` — lists photos without a reading.
2. For each photo:
   - `python -m skfs_ocr tiles input/<photo>` and Read the 4 tiles in `data/tiles/`.
     For a blurry number: `python -m skfs_ocr tiles input/<photo> --box l,t,r,b` (fractions).
   - Transcribe exactly what is written (rules: `PROMPT` in `skfs_ocr/schema.py`), and save it with
     `python -m skfs_ocr fill <photo> <<'EOF' {...compact json...} EOF` (format: `skfs_ocr/fill.py`).
   - The command prints the checks. On an ERROR, zoom into the digits involved and re-read them.
     If the page itself is wrong (e.g. the total was corrected in pen), keep what is written and
     explain it in `"u"`. Never change a number just to make a check pass unless the zoomed
     photo supports it; say so in `"u"` when a faint digit is chosen by the arithmetic.
3. `python -m skfs_ocr run --no-api` and tell the user which days are OK / CHECK / ERROR.
   This moves the used photos from `input/` to `raw_data/FY..../MM Mon-YYYY/` (FY = April-March)
   and writes `output/FY..../MM Mon-YYYY/`. To correct an already-filed photo, re-fill it by name
   (`fill` finds photos in `raw_data/` too) and run again.

Do not edit `template/template.xlsx` or files in `output/` by hand.
Run `python -m pytest -q` after any code change.
