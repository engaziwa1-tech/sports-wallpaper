"""Sports Matchup Wallpapers for Projectivy Launcher (via the Overflight plugin).

Endpoints:
  /wallpapers.json  -> Overflight-format JSON list of today's matchup images
  /playlist.m3u     -> same list as an M3U playlist (Projectivy 4.70+)
  /img/...          -> the rendered 1920x1080 PNGs
  /                 -> human-friendly status page
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

import renderer
from espn import Game, fetch_scoreboard, parse_games

# ------------------------------------------------------------------- settings

def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]

LEAGUES = _csv(os.environ.get("LEAGUES", "soccer/fifa.world,baseball/mlb"))
TEAMS = _csv(os.environ.get("TEAMS", ""))  # "USA,Braves" or scoped "hockey/nhl:BOS"
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
MAX_GAMES = int(os.environ.get("MAX_GAMES", "8"))
SHOW_ALL_IF_NO_MATCH = os.environ.get("SHOW_ALL_IF_NO_MATCH", "false").lower() == "true"

app = FastAPI(title="Sports Matchup Wallpapers")

_img_cache: OrderedDict[str, bytes] = OrderedDict()
IMG_CACHE_MAX = 48


# -------------------------------------------------------------------- helpers

def _today() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y%m%d")


def _team_matches(game: Game) -> bool:
    if not TEAMS:
        return True
    for entry in TEAMS:
        scope, _, token = entry.rpartition(":")
        if scope and scope.lower() != game.league_path.lower():
            continue
        t = token.lower()
        for side in (game.left, game.right):
            if t == side.abbrev.lower() or t in side.name.lower():
                return True
    return False


def _collect_games() -> list[Game]:
    date = _today()
    games: list[Game] = []
    for league in LEAGUES:
        try:
            games.extend(parse_games(fetch_scoreboard(league, date), league))
        except Exception:
            continue  # one league failing shouldn't kill the wallpaper feed
    matched = [g for g in games if _team_matches(g)]
    if not matched and SHOW_ALL_IF_NO_MATCH:
        matched = games
    matched.sort(key=lambda g: g.start_utc)
    return matched[:MAX_GAMES]


def _bust(game: Game) -> str:
    """Cache-buster: changes every 10 min and whenever score/status changes."""
    h = hashlib.md5(game.status_hash.encode()).hexdigest()[:8]
    return f"{int(time.time() // 600)}-{h}"


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ------------------------------------------------------------------ endpoints

@app.get("/wallpapers.json")
def wallpapers(request: Request):
    base = _base(request)
    games = _collect_games()
    if not games:
        day = _today()
        return JSONResponse([{
            "location": "Sports",
            "title": "No games today",
            "author": "ESPN",
            "url_img": f"{base}/img/none.png?v={day}",
        }])
    return JSONResponse([
        {
            "location": g.league_name,
            "title": g.title,
            "author": g.broadcast or g.venue or "ESPN",
            "url_img": f"{base}/img/{g.league_path}/{g.event_id}.png?v={_bust(g)}",
        }
        for g in games
    ])


@app.get("/playlist.m3u")
def playlist(request: Request):
    base = _base(request)
    games = _collect_games()
    lines = ["#EXTM3U"]
    if not games:
        lines += ["#EXTINF:-1,No games today", f"{base}/img/none.png?v={_today()}"]
    for g in games:
        lines += [f"#EXTINF:-1,{g.title}",
                  f"{base}/img/{g.league_path}/{g.event_id}.png?v={_bust(g)}"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="audio/x-mpegurl")


@app.get("/img/none.png")
def no_games_image():
    day = _today()
    key = f"none-{day}"
    if key not in _img_cache:
        _img_cache[key] = renderer.render_no_games(
            [l.split("/")[-1].upper() for l in LEAGUES], TIMEZONE, TEAMS)
        _trim_cache()
    return Response(_img_cache[key], media_type="image/png",
                    headers={"Cache-Control": "public, max-age=600"})


@app.get("/img/{league_path:path}/{event_id}.png")
def game_image(league_path: str, event_id: str):
    try:
        games = parse_games(fetch_scoreboard(league_path, _today()), league_path)
    except Exception:
        raise HTTPException(502, "ESPN fetch failed")
    game = next((g for g in games if g.event_id == event_id), None)
    if game is None:
        raise HTTPException(404, "Game not found for today")
    key = f"{event_id}-{hashlib.md5(game.status_hash.encode()).hexdigest()[:8]}"
    if key not in _img_cache:
        _img_cache[key] = renderer.render_game(game, TIMEZONE)
        _trim_cache()
    return Response(_img_cache[key], media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


def _trim_cache():
    while len(_img_cache) > IMG_CACHE_MAX:
        _img_cache.popitem(last=False)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    base = _base(request)
    games = _collect_games()
    rows = "".join(
        f"<li><a href='{base}/img/{g.league_path}/{g.event_id}.png?v={_bust(g)}'>"
        f"{g.league_name}: {g.title}</a> — {g.state} {g.status_detail} "
        f"— {g.broadcast or 'no broadcast listed'}</li>"
        for g in games
    ) or "<li>No games today for your teams.</li>"
    return f"""<html><body style="font-family:sans-serif;max-width:720px;margin:40px auto">
    <h2>Sports Matchup Wallpapers</h2>
    <p>Point the Overflight plugin at:
       <code>{base}/wallpapers.json</code> (or <code>{base}/playlist.m3u</code>)</p>
    <p>Leagues: <code>{', '.join(LEAGUES)}</code><br>
       Teams filter: <code>{', '.join(TEAMS) or 'all teams'}</code><br>
       Timezone: <code>{TIMEZONE}</code></p>
    <h3>Today's wallpapers</h3><ul>{rows}</ul>
    </body></html>"""
