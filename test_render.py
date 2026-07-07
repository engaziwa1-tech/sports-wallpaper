"""Render sample wallpapers offline (no ESPN access needed) to preview the design.
Run:  python3 test_render.py
"""

from datetime import datetime, timezone

import renderer
from espn import Game, TeamSide

TZ = "America/Chicago"

pre_game = Game(
    event_id="preview1",
    league_path="soccer/fifa.world",
    league_name="FIFA World Cup",
    league_logo_url="",  # offline: falls back to text pill
    start_utc=datetime(2026, 7, 6, 19, 0, tzinfo=timezone.utc),
    state="pre",
    status_detail="2:00 PM CDT",
    left=TeamSide(name="United States", short_name="USA", abbrev="USA",
                  color="0a3161", alt_color="b31942",
                  logo_url="https://a.espncdn.com/i/teamlogos/soccer/500/660.png"),
    right=TeamSide(name="Belgium", short_name="Belgium", abbrev="BEL",
                   color="8d1b3d", alt_color="fdda24",
                   logo_url="https://a.espncdn.com/i/teamlogos/soccer/500/599.png"),
    broadcast="FOX  •  Telemundo",
    venue="AT&T Stadium, Arlington",
)

live_game = Game(
    event_id="preview2",
    league_path="baseball/mlb",
    league_name="MLB",
    league_logo_url="",
    start_utc=datetime(2026, 7, 6, 23, 15, tzinfo=timezone.utc),
    state="in",
    status_detail="Bot 7th",
    left=TeamSide(name="Chicago Cubs", short_name="Cubs", abbrev="CHC",
                  color="0e3386", alt_color="cc3433", score="3",
                  logo_url="https://a.espncdn.com/i/teamlogos/mlb/500/chc.png"),
    right=TeamSide(name="Atlanta Braves", short_name="Braves", abbrev="ATL",
                   color="ce1141", alt_color="13274f", score="5",
                   logo_url="https://a.espncdn.com/i/teamlogos/mlb/500/atl.png"),
    broadcast="ESPN",
    venue="Truist Park",
)

final_game = Game(
    event_id="preview3",
    league_path="hockey/nhl",
    league_name="NHL",
    league_logo_url="",
    start_utc=datetime(2026, 7, 5, 0, 0, tzinfo=timezone.utc),
    state="post",
    status_detail="Final/OT",
    left=TeamSide(name="Boston Bruins", short_name="Bruins", abbrev="BOS",
                  color="fcb514", alt_color="000000", score="4",
                  logo_url="https://a.espncdn.com/i/teamlogos/nhl/500/bos.png"),
    right=TeamSide(name="Hartford Whalers", short_name="Whalers", abbrev="HFD",
                   color="046a38", alt_color="00205b", score="3",
                   logo_url=""),
    broadcast="ESPN+  •  Hulu",
    venue="TD Garden",
)

for name, g in (("preview_pre.png", pre_game),
                ("preview_live.png", live_game),
                ("preview_final.png", final_game)):
    with open(f"sample/{name}", "wb") as f:
        f.write(renderer.render_game(g, TZ))
    print("wrote", name)

with open("sample/preview_nogames.png", "wb") as f:
    f.write(renderer.render_no_games(["FIFA WORLD CUP", "MLB", "NHL"], TZ, ["USA", "Braves", "Bruins"]))
print("wrote preview_nogames.png")
