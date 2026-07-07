"""Fetch and parse ESPN's public scoreboard API into simple Game objects."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{league}/scoreboard"
HEADERS = {"User-Agent": "Mozilla/5.0 (SportsWallpaper/1.0; personal wallpaper generator)"}
CACHE_TTL = 120  # seconds; be polite to ESPN

# Friendly names for common league slugs (fallback when the API omits one)
LEAGUE_NAMES = {
    "soccer/fifa.world": "FIFA World Cup",
    "soccer/eng.1": "Premier League",
    "soccer/usa.1": "MLS",
    "soccer/uefa.champions": "UEFA Champions League",
    "hockey/nhl": "NHL",
    "basketball/nba": "NBA",
    "basketball/wnba": "WNBA",
    "football/nfl": "NFL",
    "football/college-football": "College Football",
    "baseball/mlb": "MLB",
    "basketball/mens-college-basketball": "College Basketball",
}

_scoreboard_cache: dict[tuple[str, str], tuple[float, dict]] = {}


@dataclass
class TeamSide:
    name: str = "TBD"
    short_name: str = "TBD"
    abbrev: str = "?"
    color: str = ""       # hex without '#'
    alt_color: str = ""
    logo_url: str = ""
    score: str = ""
    home_away: str = ""


@dataclass
class Game:
    event_id: str = ""
    league_path: str = ""
    league_name: str = ""
    league_logo_url: str = ""
    start_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: str = "pre"          # pre | in | post
    status_detail: str = ""      # e.g. "7:00 PM EDT", "45'+2'", "Final", "FT"
    left: TeamSide = field(default_factory=TeamSide)
    right: TeamSide = field(default_factory=TeamSide)
    broadcast: str = ""
    venue: str = ""

    @property
    def title(self) -> str:
        return f"{self.left.short_name} vs {self.right.short_name}"

    @property
    def status_hash(self) -> str:
        """Changes whenever the on-image content would change (used for cache busting)."""
        return f"{self.state}|{self.status_detail}|{self.left.score}-{self.right.score}"


def fetch_scoreboard(league_path: str, date_yyyymmdd: str) -> dict:
    key = (league_path, date_yyyymmdd)
    now = time.time()
    hit = _scoreboard_cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    resp = requests.get(
        SCOREBOARD_URL.format(league=league_path),
        params={"dates": date_yyyymmdd},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _scoreboard_cache[key] = (now, data)
    return data


def _parse_dt(iso: str) -> datetime:
    # ESPN uses e.g. "2026-07-06T19:00Z"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _league_info(data: dict, league_path: str) -> tuple[str, str]:
    name = LEAGUE_NAMES.get(league_path, league_path.split("/")[-1].upper())
    logo = ""
    leagues = data.get("leagues") or []
    if leagues:
        lg = leagues[0]
        name = lg.get("name") or lg.get("abbreviation") or name
        for lg_logo in lg.get("logos") or []:
            href = lg_logo.get("href")
            if href:
                logo = href
                if "default" in (lg_logo.get("rel") or []):
                    break
    return name, logo


def _parse_team(comp: dict) -> TeamSide:
    team = comp.get("team") or {}
    return TeamSide(
        name=team.get("displayName") or team.get("name") or "TBD",
        short_name=team.get("shortDisplayName") or team.get("displayName") or "TBD",
        abbrev=team.get("abbreviation") or "?",
        color=(team.get("color") or "").lstrip("#"),
        alt_color=(team.get("alternateColor") or "").lstrip("#"),
        logo_url=team.get("logo") or "",
        score=str(comp.get("score") or ""),
        home_away=comp.get("homeAway") or "",
    )


def _parse_broadcast(competition: dict) -> str:
    names: list[str] = []
    for b in competition.get("broadcasts") or []:
        for n in b.get("names") or []:
            if n and n not in names:
                names.append(n)
    if not names:
        for gb in competition.get("geoBroadcasts") or []:
            n = ((gb.get("media") or {}).get("shortName") or "").strip()
            if n and n not in names:
                names.append(n)
    return "  •  ".join(names[:3])


def parse_games(data: dict, league_path: str) -> list[Game]:
    league_name, league_logo = _league_info(data, league_path)
    sport = league_path.split("/")[0]
    games: list[Game] = []

    for event in data.get("events") or []:
        comps = event.get("competitions") or [{}]
        competition = comps[0]
        competitors = competition.get("competitors") or []
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[-1])

        # Soccer convention: home on the left ("Chelsea vs Man City").
        # US sports convention: away on the left ("BOS @ NYY").
        if sport == "soccer":
            left, right = _parse_team(home), _parse_team(away)
        else:
            left, right = _parse_team(away), _parse_team(home)

        status = (event.get("status") or {}).get("type") or {}
        venue = (competition.get("venue") or {}).get("fullName") or ""

        games.append(
            Game(
                event_id=str(event.get("id") or ""),
                league_path=league_path,
                league_name=league_name,
                league_logo_url=league_logo,
                start_utc=_parse_dt(event.get("date") or ""),
                state=status.get("state") or "pre",
                status_detail=status.get("shortDetail") or status.get("detail") or "",
                left=left,
                right=right,
                broadcast=_parse_broadcast(competition),
                venue=venue,
            )
        )
    return games
