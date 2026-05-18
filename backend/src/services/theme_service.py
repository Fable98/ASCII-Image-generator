"""
theme_service.py — Theme and palette logic for colored ASCII output

Themes produce html_colored_ascii: a <pre> block where each character
is wrapped in a <span style="color:…"> based on a palette mapping.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
from PIL import Image

import structlog

log = structlog.get_logger(__name__)

# ── Theme definitions ─────────────────────────────────────────────────────────

THEMES: dict[str, dict] = {
    "mono": {
        "description": "White on black, no color",
        "fg": "#f5f5f5",
        "bg": "#0a0a0a",
        "use_image_color": False,
    },
    "green": {
        "description": "Classic green terminal",
        "fg": "#39ff14",
        "bg": "#000000",
        "use_image_color": False,
    },
    "amber": {
        "description": "Retro amber phosphor",
        "fg": "#ffb000",
        "bg": "#0d0800",
        "use_image_color": False,
    },
    "cyan": {
        "description": "Cold cyan terminal",
        "fg": "#00e5ff",
        "bg": "#000a0d",
        "use_image_color": False,
    },
    "color": {
        "description": "True color — each char takes color from source pixel",
        "fg": "#ffffff",
        "bg": "#000000",
        "use_image_color": True,
    },
    "neon": {
        "description": "Cyberpunk neon gradient",
        "fg": None,
        "bg": "#05000f",
        "use_image_color": False,
        "gradient": ["#ff00ff", "#7b00ff", "#00e5ff"],
    },
    "sepia": {
        "description": "Warm sepia tones",
        "fg": "#c8a97e",
        "bg": "#1a1007",
        "use_image_color": False,
    },
}


def list_themes() -> list[dict]:
    return [
        {"theme_id": tid, "description": t["description"]}
        for tid, t in THEMES.items()
    ]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore


def _lerp_color(
    colors: list[str], t: float
) -> str:
    """Interpolate across a list of hex colors at position t ∈ [0,1]."""
    if len(colors) == 1:
        return colors[0]
    seg = t * (len(colors) - 1)
    idx = min(int(seg), len(colors) - 2)
    local_t = seg - idx
    r1, g1, b1 = _hex_to_rgb(colors[idx])
    r2, g2, b2 = _hex_to_rgb(colors[idx + 1])
    r = int(r1 + (r2 - r1) * local_t)
    g = int(g1 + (g2 - g1) * local_t)
    b = int(b1 + (b2 - b1) * local_t)
    return f"#{r:02x}{g:02x}{b:02x}"


def apply_theme(
    ascii_text: str,
    theme_id: str,
    source_image: Optional[Image.Image] = None,
) -> Optional[str]:
    """
    Wrap ascii_text in HTML spans with per-character color.
    Returns None for the 'mono' theme (no coloring needed).
    """
    theme = THEMES.get(theme_id, THEMES["mono"])

    if theme_id == "mono":
        return None  # Caller renders plain text

    lines = ascii_text.split("\n")
    rows = len(lines)
    cols = max(len(line) for line in lines) if lines else 1

    bg = theme["bg"]
    fg = theme.get("fg", "#ffffff")
    use_image_color = theme.get("use_image_color", False)
    gradient = theme.get("gradient")

    # Prepare source pixel colors if needed
    pixel_colors: Optional[np.ndarray] = None
    if use_image_color and source_image is not None:
        img_resized = source_image.convert("RGB").resize((cols, rows), Image.LANCZOS)
        pixel_colors = np.array(img_resized, dtype=np.uint8)

    html_lines: list[str] = []
    for row_idx, line in enumerate(lines):
        spans: list[str] = []
        for col_idx, char in enumerate(line):
            if char == " ":
                spans.append("&nbsp;")
                continue

            # Determine character color
            if use_image_color and pixel_colors is not None:
                r, g, b = pixel_colors[row_idx, min(col_idx, cols - 1)]
                color = f"#{r:02x}{g:02x}{b:02x}"
            elif gradient:
                # Vertical gradient position
                t = row_idx / max(rows - 1, 1)
                color = _lerp_color(gradient, t)
            else:
                color = fg

            escaped = char.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            spans.append(f'<span style="color:{color}">{escaped}</span>')

        html_lines.append("".join(spans))

    inner = "\n".join(html_lines)
    return (
        f'<pre style="background:{bg};font-family:monospace;'
        f'font-size:10px;line-height:1.2;margin:0;padding:8px;'
        f'overflow:auto;color:{fg or "#fff"}">'
        f"{inner}</pre>"
    )