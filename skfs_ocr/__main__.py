"""python -m skfs_ocr [run|pending|make-template]"""
import argparse
import sys
from pathlib import Path

from .config import load_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skfs_ocr", description="Ledger photos -> monthly sale workbook")
    ap.add_argument("--config", type=Path, help="config file (default config.yaml)")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="read new photos (if API key) and rebuild workbooks (default)")
    r.add_argument("--no-api", action="store_true", help="never call the Claude API")
    sub.add_parser("pending", help="list photos that still need reading, create their blank JSON")
    tl = sub.add_parser("tiles", help="save zoomed crops of a photo (for reading it in Claude Code)")
    tl.add_argument("photo", nargs="?", help="#n from `pending`, a file name or path")
    tl.add_argument("--pending", action="store_true", help="tiles for every unread photo")
    tl.add_argument("--box", help="zoom one area: left,top,right,bottom as fractions, e.g. 0.5,0.4,0.62,0.62")
    f = sub.add_parser("fill", help="save a compact transcription from stdin (see skfs_ocr/fill.py)")
    f.add_argument("photo", help="photo file name or path inside input/")
    t = sub.add_parser("make-template", help="build template/template.xlsx from a finished workbook")
    t.add_argument("sample", type=Path)
    t.add_argument("--sheet", help="day sheet to use (default: first sheet)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):   # Hindi names on Windows consoles
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    cfg = load_config(args.config)
    if args.cmd == "make-template":
        from .template_tool import make_template

        print(f"template written: {make_template(cfg, args.sample, args.sheet)}")
        return 0
    if args.cmd == "tiles":
        from .pipeline import find_photo, input_photos, load_record
        from .tiles import make_tiles

        box = tuple(float(x) for x in args.box.split(",")) if args.box else None
        out = cfg["paths"]["extracted"].parent / "tiles"
        if args.pending:
            jobs = [(f"p{i:02d}", p) for i, p in enumerate(input_photos(cfg), 1)
                    if load_record(cfg, p)[0] is None]
        else:
            photo = find_photo(cfg, args.photo or "")
            if photo is None:
                print(f"photo {args.photo} not found")
                return 2
            ids = {p: f"p{i:02d}" for i, p in enumerate(input_photos(cfg), 1)}
            jobs = [(ids.get(photo, photo.stem), photo)]
        for short, photo in jobs:
            for p in make_tiles(photo, out, box, prefix=short):
                print(p.relative_to(cfg["paths"]["extracted"].parent.parent))
        return 0
    if args.cmd == "fill":
        import json

        from .fill import fill

        from .pipeline import find_photo

        photo = find_photo(cfg, args.photo)
        if photo is None:
            print(f"photo {args.photo} not found in input/ or raw_data/")
            return 2
        for line in fill(cfg, photo, json.load(sys.stdin)):
            print(line)
        return 0
    if args.cmd == "pending":
        from .pipeline import input_photos, load_record, write_stub

        n = 0
        for i, photo in enumerate(input_photos(cfg), 1):
            rec, status = load_record(cfg, photo)
            if rec is None:
                n += 1
                if status in ("missing", "changed"):
                    write_stub(cfg, photo)
                    status = "not read"
                print(f"#{i:<3} {photo.name}   ({status})")
        print(f"{n} photo(s) pending  -> python -m skfs_ocr tiles --pending ; fill #n < reading")
        return 0
    from .pipeline import run
    from .workbook import WorkbookError

    try:
        return run(cfg, use_api=False if getattr(args, "no_api", False) else None)
    except WorkbookError as e:
        print(f"\nERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
