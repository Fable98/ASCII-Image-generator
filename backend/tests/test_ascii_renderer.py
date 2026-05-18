"""
test_ascii_renderer.py — Unit tests for the core ASCII rendering pipeline
"""
import io
import pytest
from PIL import Image

from src.models.schemas import RenderConfig
from src.services.ascii_renderer import (
    decode_frame,
    apply_transforms,
    pixels_to_ascii,
    render_frame,
)


def _make_jpeg(color=(128, 128, 128), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_png(color=(128, 128, 128), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


# ── decode_frame ──────────────────────────────────────────────────────────────

def test_decode_jpeg():
    img = decode_frame(_make_jpeg())
    assert img.mode == "RGB"


def test_decode_png():
    img = decode_frame(_make_png())
    assert img.mode == "RGB"


def test_decode_base64():
    import base64
    raw = _make_jpeg()
    b64 = base64.b64encode(raw).decode()
    img = decode_frame(b64)
    assert img.mode == "RGB"


def test_decode_base64_with_data_uri():
    import base64
    raw = _make_jpeg()
    b64 = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    img = decode_frame(b64)
    assert img.mode == "RGB"


def test_decode_invalid_raises():
    with pytest.raises(ValueError):
        decode_frame(b"not an image")


# ── pixels_to_ascii ───────────────────────────────────────────────────────────

def test_black_frame_maps_to_first_char():
    """Pure black → all pixels map to first (darkest) charset character."""
    img = Image.new("RGB", (10, 5), color=(0, 0, 0))
    charset = " .:-=+*#%@"
    result = pixels_to_ascii(img, charset, invert=False)
    for char in result.replace("\n", ""):
        assert char == charset[0], f"Expected '{charset[0]}', got '{char}'"


def test_white_frame_maps_to_last_char():
    """Pure white → all pixels map to last (brightest) charset character."""
    img = Image.new("RGB", (10, 5), color=(255, 255, 255))
    charset = " .:-=+*#%@"
    result = pixels_to_ascii(img, charset, invert=False)
    for char in result.replace("\n", ""):
        assert char == charset[-1], f"Expected '{charset[-1]}', got '{char}'"


def test_invert_reverses_mapping():
    img_black = Image.new("RGB", (4, 4), color=(0, 0, 0))
    img_white = Image.new("RGB", (4, 4), color=(255, 255, 255))
    charset = " .:-=+*#%@"

    normal_black = pixels_to_ascii(img_black, charset, invert=False)
    inverted_black = pixels_to_ascii(img_black, charset, invert=True)
    assert normal_black[0] == charset[0]
    assert inverted_black[0] == charset[-1]


def test_output_has_correct_dimensions():
    img = Image.new("RGB", (20, 10))
    charset = " .#"
    result = pixels_to_ascii(img, charset)
    lines = result.split("\n")
    assert len(lines) == 10
    assert all(len(line) == 20 for line in lines)


# ── apply_transforms ──────────────────────────────────────────────────────────

def test_flip_horizontal():
    img = Image.new("RGB", (4, 4))
    img.putpixel((0, 0), (255, 0, 0))
    config = RenderConfig(flip_horizontal=True, flip_vertical=False)
    flipped = apply_transforms(img.copy(), config)
    assert flipped.getpixel((3, 0)) == (255, 0, 0)


def test_flip_vertical():
    img = Image.new("RGB", (4, 4))
    img.putpixel((0, 0), (0, 255, 0))
    config = RenderConfig(flip_horizontal=False, flip_vertical=True)
    flipped = apply_transforms(img.copy(), config)
    assert flipped.getpixel((0, 3)) == (0, 255, 0)


def test_no_flip():
    img = Image.new("RGB", (4, 4))
    img.putpixel((1, 1), (0, 0, 255))
    config = RenderConfig(flip_horizontal=False, flip_vertical=False)
    result = apply_transforms(img.copy(), config)
    assert result.getpixel((1, 1)) == (0, 0, 255)


# ── render_frame (full pipeline) ──────────────────────────────────────────────

def test_render_frame_returns_ascii():
    config = RenderConfig(ascii_width=40)
    result = render_frame(_make_jpeg(), config)
    assert "ascii_text" in result
    assert len(result["ascii_text"]) > 0
    assert result["width"] == 40
    assert result["processing_ms"] >= 0


def test_render_frame_processing_ms_reasonable():
    config = RenderConfig(ascii_width=80)
    result = render_frame(_make_jpeg(size=(320, 240)), config)
    assert result["processing_ms"] < 2000  # Should complete in under 2s


def test_render_frame_invalid_raises():
    config = RenderConfig()
    with pytest.raises(ValueError):
        render_frame(b"garbage", config)


def test_render_frame_respects_width():
    for width in [20, 60, 120]:
        config = RenderConfig(ascii_width=width)
        result = render_frame(_make_jpeg(size=(640, 480)), config)
        assert result["width"] == width
        first_line = result["ascii_text"].split("\n")[0]
        assert len(first_line) == width