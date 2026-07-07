# Sports Matchup Wallpapers for Projectivy Launcher

Generates MFT-style matchup wallpapers (split team colors, crests, league logo,
date/time, broadcast channel, live scores) for today's games, filtered to the
teams you pick. Runs entirely in the cloud on Render's free tier and feeds
Projectivy Launcher through the **Overflight** wallpaper plugin.

Data comes from ESPN's public (unofficial) scoreboard API — no API key needed.

## Deploy to Render (one time, ~5 minutes)

1. Create a GitHub repo and push this folder to it (or upload via GitHub's web UI).
2. In [Render](https://render.com): **New → Blueprint**, connect the repo.
   Render reads `render.yaml` and creates the free web service automatically.
   (Or **New → Web Service** manually: runtime Python, build
   `pip install -r requirements.txt`, start
   `uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`.)
3. Set your environment variables (Dashboard → your service → Environment):

| Variable | Example | Notes |
|---|---|---|
| `LEAGUES` | `soccer/fifa.world,hockey/nhl,football/nfl` | Comma-separated ESPN league paths (see table below) |
| `TEAMS` | `USA,Bruins,hockey/nhl:BOS` | Abbreviation or name substring, case-insensitive. Optionally scope to a league with `league:token`. Leave **empty** to show every game in your leagues. |
| `TIMEZONE` | `America/Chicago` | For the date/time printed on the image |
| `MAX_GAMES` | `8` | Cap on wallpapers per day |
| `SHOW_ALL_IF_NO_MATCH` | `false` | If `true`, fall back to all games when your teams are idle (otherwise a "No games today" card is shown) |

4. Open `https://<your-app>.onrender.com/` — you'll see today's games with
   preview links. The feed for Projectivy is
   `https://<your-app>.onrender.com/wallpapers.json`.

### League paths

| League | Path |
|---|---|
| FIFA World Cup | `soccer/fifa.world` |
| Premier League | `soccer/eng.1` |
| MLS | `soccer/usa.1` |
| Champions League | `soccer/uefa.champions` |
| NHL | `hockey/nhl` |
| NBA | `basketball/nba` |
| WNBA | `basketball/wnba` |
| NFL | `football/nfl` |
| College Football | `football/college-football` |
| MLB | `baseball/mlb` |
| College Basketball | `basketball/mens-college-basketball` |

Any `sport/league` slug that works at
`site.api.espn.com/apis/site/v2/sports/<sport>/<league>/scoreboard` works here.

## Point Projectivy at it

Requires **Projectivy Launcher Premium** (Overflight is a premium plugin).

1. On the Shield, install **Overflight (Projectivy Plugin)** from the Play Store.
2. Projectivy **Settings → Appearance → Wallpaper → Wallpaper source → Overflight**.
3. Open the plugin's settings (gear icon) and set the media source URL to
   `https://<your-app>.onrender.com/wallpapers.json`
   (M3U alternative: `/playlist.m3u`, needs Projectivy 4.70+).
4. Set the plugin's HTTP cache low (5–10 min) so live scores refresh, and pick
   your wallpaper change interval in Projectivy's wallpaper settings.

Image URLs include a cache-busting `?v=` that changes every 10 minutes and
whenever a score/status changes, so live games update on the card.

## Free-tier notes

- Render free web services sleep after ~15 min idle; the first request after
  that takes ~30–60 s. Projectivy will just show the previous wallpaper until
  the next refresh succeeds. If you want it always warm, a free monitor like
  cron-job.org or UptimeRobot pinging `/healthz` every 10 minutes works.
- ESPN's API is unofficial and rate-limited (community estimates ~1.5k
  calls/day). This app caches scoreboards for 2 minutes and images in memory,
  which keeps usage tiny.

## Run locally

```
pip install -r requirements.txt
uvicorn app:app --reload
# open http://127.0.0.1:8000/
```

`python3 test_render.py` renders sample cards into `sample/` without network.

## Endpoints

- `/wallpapers.json` — Overflight JSON feed
- `/playlist.m3u` — same list as M3U
- `/img/<league>/<event_id>.png` — a rendered 1920x1080 card
- `/img/none.png` — the "no games today" card
- `/` — status page, `/healthz` — health check
