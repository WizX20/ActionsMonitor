"""Icon rendering — Lucide-inspired glyphs + WizX20 logo composition.

All PIL drawing functions live here. Self-contained: no imports from main.
Caches (_status_qpixmaps, _snooze_qpixmaps, _base_icon_cache, _wizx20_mark_cache,
_REVIEWER_ICON_B64) are module-level singletons; main imports the dicts directly.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QPixmap, QImage

# Mirror of main.FG_LINK — duplicated here to keep this module dependency-free.
_FG_LINK = "#FBBF24"

# Status string constants — sourced from status.py (single source of truth).
from status import (
    ST_CANCELLED as _ST_CANCELLED,
    ST_FAILURE as _ST_FAILURE,
    ST_QUEUED as _ST_QUEUED,
    ST_RUNNING as _ST_RUNNING,
    ST_SKIPPED as _ST_SKIPPED,
    ST_SUCCESS as _ST_SUCCESS,
    ST_UNKNOWN as _ST_UNKNOWN,
)

# Background fills for status icon circles (white glyph on top).
_COLOUR_BG = {
    _ST_UNKNOWN:   "#8C857F",
    _ST_QUEUED:    "#CA8A04",
    _ST_RUNNING:   "#CA8A04",
    _ST_SUCCESS:   "#22994D",
    _ST_FAILURE:   "#C53030",
    _ST_CANCELLED: "#8C857F",
    _ST_SKIPPED:   "#8C857F",
}

# Lucide-inspired status icons
# ---------------------------------------------------------------------------
_ICON_GLYPH = "#FFFFFF"  # white glyph on coloured circle — max contrast at small size

def _s(val: float, size: int, svg_size: float = 24.0, pad_frac: float = 0.18) -> float:
    """Scale an SVG coordinate to image space with padding."""
    usable = size * (1 - 2 * pad_frac)
    return val / svg_size * usable + size * pad_frac


def _sw(size: int) -> int:
    """Bold stroke width for small-icon legibility."""
    return max(3, round(size / 24 * 3.2))


def _icon_base(size: int, ss: int = 4) -> tuple[Image.Image, ImageDraw.Draw, int]:
    """Create a supersampled RGBA canvas and return (img, draw, hi_size)."""
    hi = size * ss
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), hi


def _fill_circle(draw: ImageDraw.Draw, hi: int, colour: str):
    """Filled circle — no outline, just the solid status colour."""
    pad = hi * 0.04
    draw.ellipse([pad, pad, hi - pad, hi - pad], fill=colour)


def _draw_lucide_circle_check(size: int, bg_fill: str) -> Image.Image:
    """Checkmark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Bold checkmark: (8,12)→(11,15)→(16,9)
    pts = [(_s(8, hi), _s(12.5, hi)), (_s(11, hi), _s(15.5, hi)), (_s(16.5, hi), _s(9, hi))]
    draw.line(pts, fill=_ICON_GLYPH, width=sw, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_circle_x(size: int, bg_fill: str) -> Image.Image:
    """X mark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Bold X
    draw.line([(_s(9, hi), _s(9, hi)), (_s(15, hi), _s(15, hi))], fill=_ICON_GLYPH, width=sw)
    draw.line([(_s(15, hi), _s(9, hi)), (_s(9, hi), _s(15, hi))], fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_loader(size: int, bg_fill: str) -> Image.Image:
    """Partial arc (spinner) on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    r = hi * 0.30
    cx, cy = hi / 2, hi / 2
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=-60, end=240,
             fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_clock(size: int, bg_fill: str) -> Image.Image:
    """Clock face on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Circle outline for clock face
    r = hi * 0.30
    cx, cy = hi / 2, hi / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_ICON_GLYPH, width=sw)
    # Clock hands: 12 o'clock down to center, then to ~2 o'clock
    draw.line([(cx, cy - r * 0.65), (cx, cy), (cx + r * 0.55, cy + r * 0.35)],
              fill=_ICON_GLYPH, width=sw, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_ban(size: int, bg_fill: str) -> Image.Image:
    """Ban/slash on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Diagonal slash
    draw.line([(_s(6, hi), _s(6, hi)), (_s(18, hi), _s(18, hi))],
              fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_skip_forward(size: int, bg_fill: str) -> Image.Image:
    """Skip-forward on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Filled play triangle + bar
    tri = [(_s(7, hi), _s(7, hi)), (_s(14.5, hi), _s(12, hi)), (_s(7, hi), _s(17, hi))]
    draw.polygon(tri, fill=_ICON_GLYPH)
    draw.line([(_s(16.5, hi), _s(7, hi)), (_s(16.5, hi), _s(17, hi))],
              fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_circle_help(size: int, bg_fill: str) -> Image.Image:
    """Question mark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Question mark — use a font for clean rendering
    fsize = int(hi * 0.52)
    font = None
    for fname in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"):
        try:
            font = ImageFont.truetype(fname, fsize)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "?", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (hi - tw) / 2 - bbox[0]
    ty = (hi - th) / 2 - bbox[1]
    draw.text((tx, ty), "?", fill=_ICON_GLYPH, font=font)
    return img.resize((size, size), Image.LANCZOS)


# Map status → icon drawing function
_STATUS_ICON_FUNC = {
    _ST_SUCCESS:   _draw_lucide_circle_check,
    _ST_FAILURE:   _draw_lucide_circle_x,
    _ST_RUNNING:   _draw_lucide_loader,
    _ST_QUEUED:    _draw_lucide_clock,
    _ST_CANCELLED: _draw_lucide_ban,
    _ST_SKIPPED:   _draw_lucide_skip_forward,
    _ST_UNKNOWN:   _draw_lucide_circle_help,
}


def _make_status_icon(status: str, size: int = 32) -> Image.Image:
    """Generate a Lucide-style status icon with coloured background circle."""
    bg_fill = _COLOUR_BG.get(status, _COLOUR_BG[_ST_UNKNOWN])
    func = _STATUS_ICON_FUNC.get(status, _draw_lucide_circle_help)
    return func(size, bg_fill)

# Header icons (refresh / update / help)
# ---------------------------------------------------------------------------
# --- Refresh icon (Lucide rotate-cw) for header button ---

def _make_refresh_icon(size: int = 16, colour: str = _FG_LINK) -> Image.Image:
    """Lucide rotate-cw icon: circular arrow in the given colour."""
    img, draw, hi = _icon_base(size)
    sw = max(3, round(hi / 16 * 2.2))
    cx, cy = hi / 2, hi / 2
    r = hi * 0.36
    # Arc: nearly full circle, leave gap at top-right for arrowhead
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=-30, end=300,
             fill=colour, width=sw)
    # Arrowhead at the end of the arc (top-right, pointing clockwise)
    angle = math.radians(-30)
    ax = cx + r * math.cos(angle)
    ay = cy + r * math.sin(angle)
    arrow_len = hi * 0.18
    draw.polygon([
        (ax, ay),
        (ax - arrow_len, ay - arrow_len * 0.15),
        (ax - arrow_len * 0.15, ay - arrow_len),
    ], fill=colour)
    return img.resize((size, size), Image.LANCZOS)


def _make_update_icon(size: int = 16, colour: str = _FG_LINK) -> Image.Image:
    """Lucide arrow-down-to-line icon: downward arrow above a short baseline."""
    img, draw, hi = _icon_base(size)
    sw = max(3, round(hi / 16 * 2.2))
    cx = hi / 2
    top_y = hi * 0.22
    bot_y = hi * 0.70
    draw.line([(cx, top_y), (cx, bot_y)], fill=colour, width=sw)
    head = hi * 0.18
    draw.polygon([
        (cx, bot_y + head * 0.6),
        (cx - head, bot_y - head * 0.2),
        (cx + head, bot_y - head * 0.2),
    ], fill=colour)
    base_y = hi * 0.86
    draw.line([(cx - hi * 0.26, base_y), (cx + hi * 0.26, base_y)],
              fill=colour, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _make_help_icon(size: int = 16, colour: str = _FG_LINK) -> Image.Image:
    """Lucide circle-help icon: question mark inside an outlined circle."""
    img, draw, hi = _icon_base(size)
    sw = max(3, round(hi / 16 * 2.2))
    cx, cy = hi / 2, hi / 2
    r = hi * 0.42
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=sw)
    fsize = int(hi * 0.58)
    font = None
    for fname in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"):
        try:
            font = ImageFont.truetype(fname, fsize)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "?", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (hi - tw) / 2 - bbox[0]
    ty = (hi - th) / 2 - bbox[1]
    draw.text((tx, ty), "?", fill=colour, font=font)
    return img.resize((size, size), Image.LANCZOS)

# Reviewer icons (user / bot) — inline in review badges
# ---------------------------------------------------------------------------
# --- Reviewer icons (Lucide user + bot), rendered inline inside review badges ---

def _make_user_icon(size: int, colour: str) -> Image.Image:
    """Lucide user icon: circle head + bust arc. No background."""
    img, draw, hi = _icon_base(size)
    sw = max(2, round(hi / 24 * 2.2))
    cx = hi / 2
    head_cy = hi * 0.33
    head_r  = hi * 0.20
    draw.ellipse([cx - head_r, head_cy - head_r,
                  cx + head_r, head_cy + head_r],
                 outline=colour, width=sw)
    bust_r  = hi * 0.40
    bust_cy = hi * 1.00
    draw.arc([cx - bust_r, bust_cy - bust_r,
              cx + bust_r, bust_cy + bust_r],
             start=180, end=360, fill=colour, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _make_bot_icon(size: int, colour: str) -> Image.Image:
    """Lucide bot icon: antenna + rounded-rect head + two eyes. No background."""
    img, draw, hi = _icon_base(size)
    sw = max(2, round(hi / 24 * 2.0))
    cx = hi / 2
    top = hi * 0.10
    antenna_end = hi * 0.26
    draw.line([(cx, top), (cx, antenna_end)], fill=colour, width=sw)
    dot_r = max(sw * 0.7, 1.5)
    draw.ellipse([cx - dot_r, top - dot_r, cx + dot_r, top + dot_r], fill=colour)
    head_left  = hi * 0.16
    head_right = hi * 0.84
    head_top   = antenna_end + sw
    head_bot   = hi * 0.84
    try:
        draw.rounded_rectangle(
            [head_left, head_top, head_right, head_bot],
            radius=hi * 0.13, outline=colour, width=sw,
        )
    except AttributeError:
        draw.rectangle([head_left, head_top, head_right, head_bot],
                       outline=colour, width=sw)
    eye_cy = (head_top + head_bot) / 2
    eye_r  = max(hi * 0.055, 1.5)
    for ex in (cx - hi * 0.15, cx + hi * 0.15):
        draw.ellipse([ex - eye_r, eye_cy - eye_r,
                      ex + eye_r, eye_cy + eye_r], fill=colour)
    return img.resize((size, size), Image.LANCZOS)


_REVIEWER_ICON_B64: dict[tuple[str, str, int], str] = {}


def _reviewer_icon_b64(kind: str, colour: str, px: int = 12) -> str:
    """Render reviewer glyph at `px` pixels in `colour`, return base64 PNG.
    kind: 'bot' | 'user'. Cached per (kind, colour, px)."""
    key = (kind, colour, px)
    cached = _REVIEWER_ICON_B64.get(key)
    if cached is not None:
        return cached
    img = _make_bot_icon(px, colour) if kind == "bot" else _make_user_icon(px, colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    _REVIEWER_ICON_B64[key] = data
    return data

# Snooze button icons + Qt conversion
# ---------------------------------------------------------------------------
# --- Snooze button icon (bell / bell-off) ---

_SNOOZE_ICON_SIZE = 16


def _draw_bell_glyph(draw: ImageDraw.Draw, hi: int, fg_colour: str):
    """Draw a filled bell glyph centred in a hi x hi canvas."""
    cx = hi / 2
    # Dome (top half of ellipse blended into body)
    dome_w = hi * 0.48
    dome_top = hi * 0.20
    dome_h = hi * 0.50
    draw.ellipse([cx - dome_w / 2, dome_top,
                  cx + dome_w / 2, dome_top + dome_h], fill=fg_colour)
    # Body: rectangle blending dome into rim
    body_w = hi * 0.42
    body_top = dome_top + dome_h * 0.45
    body_bot = hi * 0.66
    draw.rectangle([cx - body_w / 2, body_top,
                    cx + body_w / 2, body_bot], fill=fg_colour)
    # Flared rim (wider)
    rim_w = hi * 0.56
    rim_top = body_bot
    rim_bot = hi * 0.74
    draw.rectangle([cx - rim_w / 2, rim_top,
                    cx + rim_w / 2, rim_bot], fill=fg_colour)
    # Top pin
    pin_w = hi * 0.14
    pin_top = hi * 0.08
    pin_h = hi * 0.12
    draw.ellipse([cx - pin_w / 2, pin_top,
                  cx + pin_w / 2, pin_top + pin_h], fill=fg_colour)
    # Clapper (small circle below rim)
    cl_w = hi * 0.16
    cl_top = hi * 0.78
    draw.ellipse([cx - cl_w / 2, cl_top,
                  cx + cl_w / 2, cl_top + cl_w], fill=fg_colour)


def _make_snooze_icon(size: int = _SNOOZE_ICON_SIZE, bg_colour: str = "#3D3530",
                      fg_colour: str = "#A8A29E", off: bool = False) -> Image.Image:
    """Bell icon on a filled circle background. When `off`, adds a diagonal slash."""
    img, draw, hi = _icon_base(size)
    pad = int(hi * 0.02)
    draw.ellipse([pad, pad, hi - pad, hi - pad], fill=bg_colour)
    _draw_bell_glyph(draw, hi, fg_colour)
    if off:
        slash_start = (hi * 0.20, hi * 0.22)
        slash_end = (hi * 0.80, hi * 0.82)
        gap_w = max(4, round(hi / 16 * 5.0))
        line_w = max(2, round(hi / 16 * 2.2))
        draw.line([slash_start, slash_end], fill=bg_colour, width=gap_w)
        draw.line([slash_start, slash_end], fill=fg_colour, width=line_w)
    return img.resize((size, size), Image.LANCZOS)


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    img = pil_img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


_snooze_qpixmaps: dict[str, QPixmap] = {}


_SNOOZE_ICON_STYLES = {
    "normal":       ("#3D3530", "#A8A29E", False),
    "hover":        ("#4A3728", "#FBBF24", False),
    "active":       ("#92400E", "#FEF3C7", True),
    "active_hover": ("#78350F", "#FFFFFF", True),
}


def _init_snooze_icons():
    """Generate snooze/unsnooze button icons (normal + hover). Call after QApplication exists."""
    if _snooze_qpixmaps:
        return
    for key, (bg, fg, off) in _SNOOZE_ICON_STYLES.items():
        _snooze_qpixmaps[key] = _pil_to_qpixmap(
            _make_snooze_icon(bg_colour=bg, fg_colour=fg, off=off))

# WizX20 logo mark (embedded base64 PNG)
# ---------------------------------------------------------------------------
# WizX20 logo mark (lightning bolt) — rendered from docs/wizx20-mark.png
# 256×256 RGBA PNG, embedded so no asset file needs bundling.
_WIZX20_MARK_B64 = (
    "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"
    "YII="
)

_wizx20_mark_cache: dict[int, "Image.Image"] = {}

def _load_wizx20_mark(height: int) -> "Image.Image":
    """Decode the embedded WizX20 mark PNG and scale to the given height."""
    if height in _wizx20_mark_cache:
        return _wizx20_mark_cache[height]
    data = base64.b64decode(_WIZX20_MARK_B64)
    mark = Image.open(io.BytesIO(data)).convert("RGBA")
    w = int(mark.width * height / mark.height)
    mark = mark.resize((w, height), Image.LANCZOS)
    _wizx20_mark_cache[height] = mark
    return mark

# App / tray icon (WizX20 bolt mark on dark rounded rect + status dot)
# ---------------------------------------------------------------------------
# --- App / tray icon (WizX20 bolt mark on dark rounded rect + status dot) ---

def _make_base_icon(size: int = 64) -> Image.Image:
    """App icon: WizX20 bolt mark on dark rounded-rect background.
    At ≤32px the full mark fuses into a blob, so a simplified amber ">" chevron
    is drawn instead — readable in toasts and the taskbar."""
    img, draw, hi = _icon_base(size)

    if size <= 32:
        # Simplified amber chevron, no chrome — fills the icon area cleanly.
        cx, cy = hi // 2, hi // 2
        arm = int(hi * 0.35)
        sw = max(2, int(hi * 0.18))
        tip = (cx + arm // 2, cy)
        top = (cx - arm // 2, cy - arm)
        bot = (cx - arm // 2, cy + arm)
        draw.line([top, tip, bot], fill="#FBBF24", width=sw, joint="curve")
        return img.resize((size, size), Image.LANCZOS)

    pad = hi // 16
    radius = hi // 4
    draw.rounded_rectangle([pad, pad, hi - pad, hi - pad],
                           radius=radius, fill="#252220")
    inner_pad = pad + hi // 32
    inner_radius = radius - hi // 32
    draw.rounded_rectangle([inner_pad, inner_pad, hi - inner_pad, hi - inner_pad],
                           radius=inner_radius, fill="#2D2926")

    # WizX20 bolt mark — composited from embedded PNG
    mark_pad = hi // 10
    mark_h = hi - 2 * (inner_pad + mark_pad)
    mark = _load_wizx20_mark(mark_h)
    mx = (hi - mark.width) // 2
    my = (hi - mark.height) // 2
    img.paste(mark, (mx, my), mark)

    return img.resize((size, size), Image.LANCZOS)


_base_icon_cache: dict[int, Image.Image] = {}


def _make_icon_image(colour: str, size: int = 64) -> Image.Image:
    """Base icon with a coloured status dot in the bottom-right corner."""
    if size not in _base_icon_cache:
        _base_icon_cache[size] = _make_base_icon(size)
    img = _base_icon_cache[size].copy()
    ss = 4
    hi = size * ss
    overlay = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    dot_r = hi // 5
    x = hi - dot_r - ss
    y = hi - dot_r - ss
    draw.ellipse([x - dot_r - 3*ss, y - dot_r - 3*ss,
                  x + dot_r + 3*ss, y + dot_r + 3*ss], fill="#1C1917")
    draw.ellipse([x - dot_r - ss, y - dot_r - ss,
                  x + dot_r + ss, y + dot_r + ss], fill="#FFFFFF")
    draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=colour)

    overlay = overlay.resize((size, size), Image.LANCZOS)
    img.paste(overlay, (0, 0), overlay)
    return img


# File generators (called once at startup with explicit paths)
# ---------------------------------------------------------------------------

def _generate_app_ico(path: Path) -> None:
    """Generate app.ico with multiple sizes for crisp display at all scales.
    Regenerated every startup so icon design changes take effect without
    requiring users to delete the existing file."""
    try:
        sizes = [256, 48, 32, 16]  # largest first for proper ICO embedding
        images = [_make_base_icon(s) for s in sizes]
        images[0].save(str(path), format="ICO",
                       sizes=[(s, s) for s in sizes],
                       append_images=images[1:])
    except Exception as exc:
        print(f"[Icon] Generate error: {exc}")


def _generate_check_glyph(path: Path) -> None:
    """Generate a white check-mark PNG used as the QCheckBox indicator image
    in the dark-theme stylesheet. Rendered at 4x supersample + LANCZOS for
    clean edges at 14x14 display size. Regenerated every startup."""
    try:
        size, scale = 14, 4
        hi = size * scale
        img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        sw = max(2, int(hi * 0.16))
        pts = [
            (hi * 0.22, hi * 0.54),
            (hi * 0.44, hi * 0.74),
            (hi * 0.80, hi * 0.30),
        ]
        draw.line(pts, fill="#FFFFFF", width=sw, joint="curve")
        img.resize((size, size), Image.LANCZOS).save(str(path), format="PNG")
    except Exception as exc:
        print(f"[Check glyph] Generate error: {exc}")

# Status icon QPixmap cache
# ---------------------------------------------------------------------------
# Pre-generated status icon QPixmaps (populated once QApplication exists)
_status_qpixmaps: dict[str, QPixmap] = {}
_ICON_SIZE = 24  # px for row status icons


def _init_status_icons():
    """Generate and cache QPixmap icons for all statuses. Call after QApplication exists."""
    if _status_qpixmaps:
        return
    for st in (_ST_UNKNOWN, _ST_QUEUED, _ST_RUNNING, _ST_SUCCESS,
               _ST_FAILURE, _ST_CANCELLED, _ST_SKIPPED):
        img = _make_status_icon(st, _ICON_SIZE)
        _status_qpixmaps[st] = _pil_to_qpixmap(img)
