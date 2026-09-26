"""Photo -> transcription JSON (via Claude), cached per photo.

Each photo gets data/extracted/<YYYY-MM>/<photo name>.json. If that file
exists and the photo has not changed, Claude is NOT called again, so
re-running a month costs zero tokens. You can also open the JSON, fix a
digit by hand, and re-run: your fix is kept.
"""
import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

from .schema import EXTRACTION_SCHEMA, PROMPT, RETRY_PROMPT

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
    IMAGE_EXTS |= {".heic", ".heif"}
except ImportError:
    pass


class ExtractionError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_image(path: Path, max_side: int, quality: int) -> bytes:
    """Fix phone rotation, shrink to max_side, boost contrast, return JPEG bytes."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=1)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


def save_record(cache_file: Path, record: dict) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists():
        old = json.loads(cache_file.read_text(encoding="utf-8"))
        if old.get("sha256") != record["sha256"]:
            cache_file.with_suffix(".json.bak").write_text(
                json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    cache_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def blank_extraction() -> dict:
    """Empty transcription, for typing a page in by hand (--manual)."""
    from .schema import PAYMENT_KEYS

    return {
        "date_text": None,
        "weekday": None,
        "rates": {"petrol": None, "diesel": None, "power": None},
        "nozzles": [],
        "sale_total": None,
        "payments": {k: None for k in PAYMENT_KEYS},
        "other_payments": [],
        "credit_entries": [],
        "unclear": [],
    }


class ClaudeReader:
    def __init__(self, cfg: dict, parties: list[str]):
        import anthropic

        self.cfg = cfg["claude"]
        self.prompt = PROMPT.replace("{parties}", ", ".join(parties) or "(none yet)")
        self.client = anthropic.Anthropic()
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def _call(self, image_b64: str, text: str) -> dict:
        c = self.cfg
        kwargs = dict(
            model=c["model"],
            max_tokens=c["max_tokens"],
            thinking={"type": "adaptive"},
            output_config={
                "effort": c["effort"],
                "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": text},
                ],
            }],
        )
        if c.get("use_fallbacks", True):
            # If Claude declines, the API re-runs the request on a fallback model.
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            response = self.client.messages.create(**kwargs)

        self.usage["input_tokens"] += response.usage.input_tokens
        self.usage["output_tokens"] += response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined to read this photo")
        if response.stop_reason == "max_tokens":
            raise ExtractionError("reply was cut off - raise claude.max_tokens in config.yaml")
        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block is None:
            raise ExtractionError("Claude returned no transcription")
        return json.loads(text_block.text)

    def read(self, photo: Path) -> dict:
        data = prepare_image(photo, self.cfg["max_image_side"], self.cfg["jpeg_quality"])
        self._image_b64 = base64.standard_b64encode(data).decode("ascii")
        return self._call(self._image_b64, self.prompt)

    def reread(self, previous: dict, problems: list[str]) -> dict:
        """Second look at the same photo, told exactly which checks failed."""
        text = self.prompt + "\n" + RETRY_PROMPT.format(
            problems="\n".join(f"- {p}" for p in problems),
            previous=json.dumps(previous, ensure_ascii=False),
        )
        return self._call(self._image_b64, text)
