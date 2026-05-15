"""
ascii_renderer.py — Core frame → ASCII conversion pipeline

Pipeline stages:
  1. Decode frame  (JPEG / WebP / PNG / base64)
  2. Apply flip transforms
  3. Brightness + contrast adjustments
  4. Grayscale + resize to character grid
  5. Intensity → charset mapping
"""
from __future__ import annotations

import base64
import io
import time
from typing import Optional, Union

import numpy as np
import structlog
from PIL import Image, ImageEnhance, ImageOps

from src.models.schemas import RenderConfig

log = structlog.get_logger(__name__)

SUPPORTED_FORMATS = {"JPEG", "WEBP", "PNG", "GIF", "BMP"}

# Charset presets (shortest = darkest when invert=False)
CHARSETS = {
    "default":  " .:-=+*#%@",
    "dense":    " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "blocks":   " ░▒▓█",
    "minimal":  " .+#",
    "braille":  " ⠂⠆⠖⠶⠷⠿⣿",
}


def decode_frame(data: Union[bytes, str]) -> Image.Image:
    """
    Decode raw bytes or base64-encoded string into a PIL Image.
    Raises ValueError on unsupported format or decode failure.
    """
    if isinstance(data, str):
        # Strip data-URI prefix if present
        if "," in data:
            data = data.split(",", 1)[1]
        try:
            data = base64.b64decode(data)
        except Exception as e:
            raise ValueError(f"Base64 decode failed: {e}") from e

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # check integrity
    except Exception as e:
        raise ValueError(f"Image decode failed: {e}") from e

    # Re-open after verify (verify() exhausts the stream)
    img = Image.open(io.BytesIO(data))

    if img.format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format: {img.format}")

    return img.convert("RGB")


def apply_transforms(img: Image.Image, config: RenderConfig) -> Image.Image:
    """Apply flip transforms per RenderConfig."""
    if config.flip_horizontal:
        img = ImageOps.mirror(img)
    if config.flip_vertical:
        img = ImageOps.flip(img)
    return img


def adjust_image(img: Image.Image, config: RenderConfig) -> Image.Image:
    """Apply brightness and contrast adjustments."""
    if config.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(config.brightness)
    if config.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(config.contrast)
    return img


def resize_to_grid(img: Image.Image, ascii_width: int) -> tuple[Image.Image, int, int]:
    """
    Resize image to fit the target character grid.
    Character cells are ~2:1 height:width, so we halve the row count.
    Returns (resized_img, cols, rows).
    """
    orig_w, orig_h = img.size
    ratio = orig_h / orig_w
    ascii_height = max(1, int(ascii_width * ratio * 0.45))
    resized = img.resize((ascii_width, ascii_height), Image.LANCZOS)
    return resized, ascii_width, ascii_height


def pixels_to_ascii(
    img: Image.Image,
    charset: str,
    invert: bool = False,
) -> str:
    """
    Map each pixel's luminance to a character in charset.
    Uses Rec.601 luma weights: Y = 0.299R + 0.587G + 0.114B
    """
    rgb = np.array(img, dtype=np.float32)
    luma = (0.299 * rgb[:, :, 0] +
            0.587 * rgb[:, :, 1] +
            0.114 * rgb[:, :, 2])          # shape: (rows, cols), 0–255

    n = len(charset) - 1
    indices = (luma / 255.0 * n).clip(0, n).astype(np.uint8)

    if invert:
        indices = n - indices

    chars = np.array(list(charset))[indices]
    rows = ["".join(row) for row in chars]
    return "\n".join(rows)


def render_frame(
    raw_data: Union[bytes, str],
    config: RenderConfig,
) -> dict:
    """
    Full pipeline: raw frame bytes → ASCII output dict.

    Returns:
        {
            "ascii_text": str,
            "width": int,
            "height": int,
            "processing_ms": float,
        }
    Raises ValueError on decode/format errors.
    """
    t0 = time.perf_counter()

    # Stage 1: Decode
    img = decode_frame(raw_data)

    # Stage 2: Flip transforms
    img = apply_transforms(img, config)

    # Stage 3: Brightness / contrast
    img = adjust_image(img, config)

    # Stage 4: Grayscale + resize
    img_gray = img.convert("L").convert("RGB")  # keep RGB shape for luma calc
    _, cols, rows = resize_to_grid(img_gray, config.ascii_width)
    img_resized, cols, rows = resize_to_grid(img_gray, config.ascii_width)

    # Stage 5: Map to charset
    charset = CHARSETS.get(config.ascii_charset, config.ascii_charset)
    ascii_text = pixels_to_ascii(img_resized, charset, config.invert)

    processing_ms = (time.perf_counter() - t0) * 1000

    log.debug(
        "frame.rendered",
        cols=cols, rows=rows,
        charset_len=len(charset),
        processing_ms=round(processing_ms, 2),
    )

    return {
        "ascii_text": ascii_text,
        "width": cols,
        "height": rows,
        "processing_ms": round(processing_ms, 2),
        "source_image": img,  # passed to theme service
    }