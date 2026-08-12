"""Render the Oracle-X brand mark to the raster formats browsers ask for.

Pillow cannot parse SVG, so the geometry of `frontend/app/icon.svg` is redrawn
here. When the mark changes, update both files together and re-run:

    python3 scripts/generate_brand_assets.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

# ── Design grid ──────────────────────────────────────────────────────────────
# Measurements use the same 32-unit grid as the SVG, scaled to the pixel size
# being rendered.
GRID = 32.0
CENTER = 16.0
CORNER_RADIUS = 7.0

# The ring is reduced to four reticle ticks centred on the axes, each spanning
# 44 degrees. Angles follow Pillow's convention: 0 is 3 o'clock, growing
# clockwise.
RING_RADIUS = 9.0
RING_STROKE = 2.4
TICK_CENTERS: tuple[float, ...] = (270.0, 0.0, 90.0, 180.0)
TICK_HALF_SPAN = 22.0

# The X overshoots the ring: a contained X would read as a "close" glyph.
ARM_RADIUS = 12.6
ARM_STROKE = 2.1
ARM_ANGLES: tuple[float, ...] = (45.0, 135.0)

CAPSULE = "#111114"  # --surface
MARK = "#e8e8ea"  # --fg

# Pillow draws primitives without antialiasing, so the mark is rendered large
# and resampled down.
SUPERSAMPLE = 16

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "frontend" / "app"
ICO_SIZES = (16, 32, 48)
APPLE_ICON_SIZE = 180


def render(size: int, *, rounded: bool = True) -> Image.Image:
    """Draw the mark as a `size`x`size` RGBA image.

    `rounded` is off for the Apple touch icon: iOS applies its own corner mask,
    and pre-rounded corners show through it as dark notches.
    """
    canvas = size * SUPERSAMPLE
    unit = canvas / GRID
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    edge = canvas - 1
    if rounded:
        draw.rounded_rectangle((0, 0, edge, edge), CORNER_RADIUS * unit, fill=CAPSULE)
    else:
        draw.rectangle((0, 0, edge, edge), fill=CAPSULE)

    ring_box = (
        (CENTER - RING_RADIUS) * unit,
        (CENTER - RING_RADIUS) * unit,
        (CENTER + RING_RADIUS) * unit,
        (CENTER + RING_RADIUS) * unit,
    )
    ring_stroke = max(1, round(RING_STROKE * unit))
    for center in TICK_CENTERS:
        start, end = center - TICK_HALF_SPAN, center + TICK_HALF_SPAN
        draw.arc(ring_box, start, end, fill=MARK, width=ring_stroke)

    origin = CENTER * unit
    arm_stroke = max(1, round(ARM_STROKE * unit))
    for angle in ARM_ANGLES:
        dx = math.cos(math.radians(angle)) * ARM_RADIUS * unit
        dy = math.sin(math.radians(angle)) * ARM_RADIUS * unit
        draw.line(
            (origin - dx, origin - dy, origin + dx, origin + dy),
            fill=MARK,
            width=arm_stroke,
        )

    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    # Each ICO entry is rendered at its own size rather than downscaled from the
    # largest — Pillow reuses an appended image whenever the size matches.
    frames = [render(size) for size in sorted(ICO_SIZES)]
    largest = frames[-1]
    ico_path = APP_DIR / "favicon.ico"
    largest.save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[:-1],
    )
    print(f"wrote {ico_path.relative_to(REPO_ROOT)} ({', '.join(map(str, ICO_SIZES))})")

    # Apple drops the alpha channel anyway; flattening here keeps the file small.
    apple_path = APP_DIR / "apple-icon.png"
    render(APPLE_ICON_SIZE, rounded=False).convert("RGB").save(apple_path, format="PNG")
    print(f"wrote {apple_path.relative_to(REPO_ROOT)} ({APPLE_ICON_SIZE}px)")


if __name__ == "__main__":
    main()
