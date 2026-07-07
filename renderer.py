"""Render 1920x1080 matchup wallpapers (split team colors, crests, VS badge,
league logo, date/time, broadcast) in the style of MFT matchup cards."""

from __future__ import annotations

import io
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
    # Prefer a color that is neither near-white nor near-black and has some chroma
    for c in candidates:
        if 0.10 <= _lum(c) <= 0.72 and _sat(c) >= 0.15:
            return c
    for c in candidates:
        if 0.10 <= _lum(c) <= 0.80:
            return c
    c = candidates[0]
    if _lum(c) > 0.72:  # near white -> darken hard
        return _scale(c, 0.45) if _sat(c) > 0.05 else (38, 46, 66)
    if _lum(c) < 0.08:  # near black -> lift slightly
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
    shadow.putalpha(a.point(lambda v: int(v * 0.45)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
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

    # Concentric rings around each crest (the MFT signature)
    rings = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    for cx, bg in ((LEFT_CX, left_rgb), (RIGHT_CX, right_rgb)):
        tone = (255, 255, 255, 16) if _lum(bg) < 0.55 else (0, 0, 0, 20)
        for r in (255, 335, 415, 495):
            rd.ellipse([cx - r, LOGO_CY - r, cx + r, LOGO_CY + r], outline=tone, width=3)
    img.alpha_composite(rings)

    # Gradient bands top & bottom so overlay text is readable on any color
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(180):
        gd.line([(0, i), (W, i)], fill=(0, 0, 0, int(80 * (1 - i / 180))))
    for i in range(320):
        y = H - 320 + i
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, int(135 * (i / 320))))
    img.alpha_composite(grad)

    # Center divider
    d = ImageDraw.Draw(img)
    d.rectangle([W // 2 - 3, 0, W // 2 + 3, H], fill=(255, 255, 255, 215))
    return img


def _league_header(img: Image.Image, game: Game):
    d = ImageDraw.Draw(img)
    logo = fetch_asset(game.league_logo_url)
    if logo:
        art = logo.copy()
        art.thumbnail((470, 116), Image.LANCZOS)
        pw, ph = art.width + 64, art.height + 36
        x0, y0 = (W - pw) // 2, 52
        img.alpha_composite(art, ((W - art.width) // 2, y0 + 8))
    else:
        f = _font(FONT_BOLD, 52)
        tw, th = _tsize(d, game.league_name.upper(), f)
        pw, ph = tw + 76, th + 44
        x0, y0 = (W - pw) // 2, 56
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=26, fill=(6, 10, 20, 96))
        d.text(((W - tw) / 2, y0 + 20), game.league_name.upper(), font=f, fill=(255, 255, 255, 245))


def _center_badge(img: Image.Image, game: Game):
    d = ImageDraw.Draw(img)
    cx, cy = W // 2, LOGO_CY
    if game.state == "pre":
        r = 88
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(13, 22, 43, 255),
                  outline=(255, 255, 255, 255), width=7)
        f = _font(FONT_BOLD, 60)
        tw, th = _tsize(d, "VS", f)
        d.text((cx - tw / 2, cy - th / 2 - 8), "VS", font=f, fill=(255, 255, 255, 255))
    else:
        score = f"{game.left.score or '0'} - {game.right.score or '0'}"
        f = _fit_font(d, score, FONT_BOLD, 96, 330)
        tw, th = _tsize(d, score, f)
        bw, bh = max(tw + 110, 340), 168
        d.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
                            radius=30, fill=(13, 22, 43, 242),
                            outline=(255, 255, 255, 255), width=6)
        status=(game.status_text if hasattr(game,"status_text") else ("LIVE" if game.state=="in" else "FINAL")).upper()
        sf=_font(FONT_BOLD,34)
        stw,sth=_tsize(d,status,sf)
        d.text((cx-stw/2, cy-bh/2+18),status,font=sf,fill=(255,255,255,255))
        d.text((cx - tw / 2, cy - th / 2 + 14), score, font=f, fill=(255, 255, 255, 255))


def _bottom_block(img: Image.Image, game: Game, tz: ZoneInfo):
    d = ImageDraw.Draw(img)
    cx = W // 2
    local = game.start_utc.astimezone(tz)
    date_s = local.strftime("%A, %B %-d")
    time_s = local.strftime("%-I:%M %p %Z")

    if game.state == "pre":
        line1 = f"{date_s}   •   {time_s}"
        _center_text(d, cx, 852, line1, FONT_BOLD, 58, 1700)
    elif game.state == "in":
        detail = game.status_detail or "LIVE"
        f = _center_text(d, cx + 26, 852, f"LIVE   •   {detail}", FONT_BOLD, 58, 1600)
        tw, th = _tsize(d, f"LIVE   •   {detail}", f)
        dot_x = cx + 26 - tw / 2 - 44
        d.ellipse([dot_x - 15, 852 + th / 2 - 13, dot_x + 15, 852 + th / 2 + 17],
                  fill=(232, 55, 55, 255))
    else:
        detail = (game.status_detail or "FINAL").upper()
        detail = {"FT": "FULL TIME"}.get(detail, detail)
        _center_text(d, cx, 852, f"{detail}   •   {date_s}", FONT_BOLD, 58, 1700)

    y = 936
    if game.broadcast:
        _center_text(d,cx,y,game.broadcast.split(",")[0],FONT_REG,46,1700,fill=(255,255,255,240))
        y += 66
    if game.venue:
        _center_text(d, cx, y, game.venue, FONT_REG, 36, 1500, fill=(255, 255, 255, 185))


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
    _center_badge(img, game)
    _bottom_block(img, game, tz)

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
