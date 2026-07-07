"""Render 1920x1080 matchup wallpapers (split team colors, crests, VS badge,
league logo, date/time, broadcast) in the style of MFT matchup cards."""

from __future__ import annotations

import io
import re
import colorsys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from espn import Game

W, H = 1920, 1080
LEFT_CX, RIGHT_CX, LOGO_CY = 480, 1440, 468
FONT_BOLD = "fonts/DejaVuSans-Bold.ttf"
FONT_REG = "fonts/DejaVuSans.ttf"
HEADERS = {"User-Agent": "Mozilla/5.0 (SportsWallpaper/1.0)"}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_image_cache: dict[str, Image.Image | None] = {}


# ---------------------------------------------------------------- color utils

def _hex_rgb(h: str) -> tuple[int, int, int] | None:
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return None


def _lum(rgb) -> float:
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _sat(rgb) -> float:
    r, g, b = (c / 255 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)[1]


def _scale(rgb, f: float):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def pick_bg(color: str, alt: str) -> tuple[int, int, int]:
    """Pick a background color that reads well behind white text/logos."""
    candidates = [c for c in (_hex_rgb(color), _hex_rgb(alt)) if c]
    if not candidates:
        return (30, 41, 66)
    for c in candidates:
        if 0.10 <= _lum(c) <= 0.72 and _sat(c) >= 0.15:
            return c
    for c in candidates:
        if 0.10 <= _lum(c) <= 0.80:
            return c
    c = candidates[0]
    if _lum(c) > 0.72:
        return _scale(c, 0.45) if _sat(c) > 0.05 else (38, 46, 66)
    if _lum(c) < 0.08:
        return tuple(min(255, v + 28) for v in c)  # type: ignore
    return c


def ensure_distinct(a, b):
    """If both halves land on nearly the same color, darken the right side."""
    dist = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    if dist < 60:
        b = _scale(b, 0.62)
    return a, b


# --------------------------------------------------------------- image assets

def fetch_asset(url: str) -> Image.Image | None:
    if not url:
        return None
    if url in _image_cache:
        return _image_cache[url]
    img = None
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        img = None
    _image_cache[url] = img
    if len(_image_cache) > 200:
        _image_cache.pop(next(iter(_image_cache)))
    return img


def fallback_crest(abbrev: str, bg_rgb) -> Image.Image:
    """Simple shield with the team abbreviation, used if a logo can't load."""
    w, h = 400, 440
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(24, 20), (w - 24, 20), (w - 24, h * 0.58), (w // 2, h - 16), (24, h * 0.58)]
    d.polygon(pts, fill=(248, 249, 252, 255))
    d.line(pts + [pts[0]], fill=_scale(bg_rgb, 0.55) + (255,), width=14, joint="curve")
    f = _font(FONT_BOLD, 128 if len(abbrev) <= 3 else 96)
    tw, th = _tsize(d, abbrev, f)
    d.text(((w - tw) / 2, (h * 0.86 - th) / 2), abbrev, font=f, fill=_scale(bg_rgb, 0.6) + (255,))
    return img


def _fit(img: Image.Image, box: int) -> Image.Image:
    im = img.copy()
    im.thumbnail((box, box), Image.LANCZOS)
    return im


def _shadowed_paste(canvas: Image.Image, art: Image.Image, cx: int, cy: int):
    """Paste artwork centered at (cx, cy) with a soft drop shadow."""
    a = art.split()[3]
    shadow = Image.new("RGBA", art.size, (0, 0, 0, 0))
    shadow.putalpha(a.point(lambda v: int(v * 0.75)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    x, y = cx - art.width // 2, cy - art.height // 2
    canvas.alpha_composite(shadow, (x, y + 14))
    canvas.alpha_composite(art, (x, y))


# ----------------------------------------------------------------- text utils

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def _tsize(d: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _fit_font(d, text: str, path: str, size: int, max_w: int):
    f = _font(path, size)
    while size > 22 and _tsize(d, text, f)[0] > max_w:
        size -= 4
        f = _font(path, size)
    return f


def _center_text(d, cx, y, text, path, size, max_w, fill=(255, 255, 255, 255), shadow=True):
    f = _fit_font(d, text, path, size, max_w)
    tw, _ = _tsize(d, text, f)
    x = cx - tw / 2
    if shadow:
        d.text((x, y + 3), text, font=f, fill=(0, 0, 0, 130))
    d.text((x, y), text, font=f, fill=fill)
    return f


# ------------------------------------------------------------------ rendering

def _base_canvas(left_rgb, right_rgb) -> Image.Image:
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W // 2, H], fill=left_rgb + (255,))
    d.rectangle([W // 2, 0, W, H], fill=right_rgb + (255,))

    rings = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    for cx, bg in ((LEFT_CX, left_rgb), (RIGHT_CX, right_rgb)):
        tone = (255, 255, 255, 16) if _lum(bg) < 0.55 else (0, 0, 0, 20)
        for r in (255, 335, 415, 495):
            rd.ellipse([cx - r, LOGO_CY - r, cx + r, LOGO_CY + r], outline=tone, width=3)
    img.alpha_composite(rings)

    # Gradient band solely at the top so league text stays readable
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(180):
        gd.line([(0, i), (W, i)], fill=(0, 0, 0, int(80 * (1 - i / 180))))
    img.alpha_composite(grad)

    d = ImageDraw.Draw(img)
    d.rectangle([W // 2 - 3, 0, W // 2 + 3, H], fill=(255, 255, 255, 215))
    return img


def _league_header(img: Image.Image, game: Game):
    d = ImageDraw.Draw(img)
    logo = fetch_asset(game.league_logo_url)
    if logo:
        art = logo.copy()
        art.thumbnail((470, 116), Image.LANCZOS)
        _shadowed_paste(img, art, W // 2, 52 + art.height // 2)
    else:
        _center_text(d, W // 2, 56, game.league_name.upper(), FONT_BOLD, 52, 600, shadow=True)


def _center_badge(img: Image.Image, game: Game, tz: ZoneInfo):
    d = ImageDraw.Draw(img)
    cx, cy = W // 2, LOGO_CY
    local = game.start_utc.astimezone(tz)
    date_s = local.strftime("%A, %B %-d")
    time_s = local.strftime("%-I:%M %p %Z")

    is_live = False
    
    # Setup Score (Top) and Details (Bottom) strings 
    if game.state == "pre":
        score_text = "VS"
        score_size = 72
        detail_text = f"{date_s}   •   {time_s}"
    elif game.state == "in":
        score_text = f"{game.left.score or '0'} - {game.right.score or '0'}"
        score_size = 96
        detail = game.status_detail or "LIVE"
        detail_text = f"LIVE   •   {detail}"
        is_live = True
    else:
        detail = (game.status_detail or "FINAL").upper()
        detail = {"FT": "FULL TIME"}.get(detail, detail)
        score_text = f"{game.left.score or '0'} - {game.right.score or '0'}"
        score_size = 96
        detail_text = f"{detail}   •   {date_s}"

    # Measure texts
    f_score = _fit_font(d, score_text, FONT_BOLD, score_size, 330)
    tw_score, th_score = _tsize(d, score_text, f_score)

    f_detail = _font(FONT_BOLD, 26)
    tw_detail, th_detail = _tsize(d, detail_text, f_detail)

    # Extra space for live dot
    dot_space = 36 if is_live else 0
    total_detail_w = tw_detail + dot_space

    bw = max(total_detail_w + 60, tw_score + 100, 320)
    bh = th_score + th_detail + 40

    box_top = cy - bh / 2
    d.rounded_rectangle([cx - bw / 2, box_top, cx + bw / 2, box_top + bh],
                        radius=24, fill=(13, 22, 43, 242),
                        outline=(255, 255, 255, 255), width=5)

    # Render Main Score/VS (Top)
    score_y = box_top + 12
    _center_text(d, cx, score_y, score_text, FONT_BOLD, score_size, 330, shadow=False)

    # Render Detail (Bottom)
    detail_y = score_y + th_score + 8
    if is_live:
        text_x = cx + 12
        _center_text(d, text_x, detail_y, detail_text, FONT_BOLD, 26, bw, shadow=False)
        tw_detail_actual, _ = _tsize(d, detail_text, f_detail)
        
        # Red Dot 
        dot_r = 7
        dot_cx = text_x - tw_detail_actual / 2 - 16
        dot_cy = detail_y + th_detail / 2 + 2
        d.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=(232, 55, 55, 255))
    else:
        _center_text(d, cx, detail_y, detail_text, FONT_BOLD, 26, bw, shadow=False)

    # Render broadcast channel beneath the box 
    if game.broadcast:
        # Splits cleanly on comma, forward-slash, or pipe delimiters to isolate a single channel
        single_channel = re.split(r'[,/|]', game.broadcast)[0].strip()
        _center_text(d, cx, box_top + bh + 16, single_channel, FONT_BOLD, 28, 400, fill=(255, 255, 255, 240))


def render_game(game: Game, tz_name: str) -> bytes:
    tz = ZoneInfo(tz_name)
    left_rgb = pick_bg(game.left.color, game.left.alt_color)
    right_rgb = pick_bg(game.right.color, game.right.alt_color)
    left_rgb, right_rgb = ensure_distinct(left_rgb, right_rgb)

    img = _base_canvas(left_rgb, right_rgb)

    for side, cx, bg in ((game.left, LEFT_CX, left_rgb), (game.right, RIGHT_CX, right_rgb)):
        logo = fetch_asset(side.logo_url)
        art = _fit(logo, 430) if logo else fallback_crest(side.abbrev, bg)
        _shadowed_paste(img, art, cx, LOGO_CY)

    d = ImageDraw.Draw(img)
    for side, cx, bg in ((game.left, LEFT_CX, left_rgb), (game.right, RIGHT_CX, right_rgb)):
        fill = (255, 255, 255, 255) if _lum(bg) < 0.58 else (14, 20, 34, 255)
        _center_text(d, cx, 738, side.short_name.upper(), FONT_BOLD, 60, 830, fill=fill)

    _league_header(img, game)
    _center_badge(img, game, tz)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_no_games(league_names: list[str], tz_name: str, teams: list[str]) -> bytes:
    tz = ZoneInfo(tz_name)
    img = Image.new("RGBA", (W, H), (16, 24, 40, 255))
    d = ImageDraw.Draw(img)
    for r in (260, 360, 460, 560):
        d.ellipse([W / 2 - r, H / 2 - r - 40, W / 2 + r, H / 2 + r - 40],
                  outline=(255, 255, 255, 14), width=3)
    _center_text(d, W // 2, 420, "NO GAMES TODAY", FONT_BOLD, 96, 1700)
    today = datetime.now(tz).strftime("%A, %B %-d")
    _center_text(d, W // 2, 560, today, FONT_REG, 50, 1500, fill=(255, 255, 255, 210))
    scope = ", ".join(teams) if teams else ", ".join(league_names)
    if scope:
        _center_text(d, W // 2, 650, f"Watching:  {scope}", FONT_REG, 38, 1600,
                     fill=(255, 255, 255, 160))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
