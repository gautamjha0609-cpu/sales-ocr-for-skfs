"""Cut a ledger photo into 4 zoomed tiles (left/right page, top/bottom).

Used when Claude Code reads a photo itself (no API key): four 2x crops are
far easier to read than one full photo, so fewer digits are misread.
"""
from pathlib import Path

from PIL import Image, ImageOps

BOXES = {  # fractions of width/height for the usual two-page spread
    "1_left_top": (0.08, 0.00, 0.45, 0.55),
    "2_left_bottom": (0.08, 0.45, 0.45, 1.00),
    "3_right_top": (0.40, 0.05, 0.75, 0.62),
    "4_right_bottom": (0.40, 0.55, 0.75, 1.00),
}


def make_tiles(photo: Path, out_dir: Path, box: tuple | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(photo) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        boxes = {"zoom": box} if box else BOXES
        paths = []
        for name, (a, b, c, d) in boxes.items():
            t = im.crop((int(a * w), int(b * h), int(c * w), int(d * h)))
            scale = 4 if box else 2
            t = ImageOps.autocontrast(t.resize((t.width * scale, t.height * scale), Image.LANCZOS), cutoff=1)
            p = out_dir / f"{photo.stem}_{name}.png"
            t.save(p)
            paths.append(p)
    return paths
