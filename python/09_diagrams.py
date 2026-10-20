"""Explainer diagrams for the family page (docs/story.md), drawn with the
family's famdiagram (theme-aware SVG, colors as classes only). Every number
in them is read from a committed, R-reconciled output or from the pipeline's
own rule constants; team names and the date come from the LeagueGameLog
table the study already checks finals against.

  dg1_one_game       the rule read on one real game: the trigger, the target,
                     the moment a team reaches it, and the real final
                     (output/replay_games.csv)
  dg2_three_answers  a Sankey of the NBA regular season's games through the
                     tiers: the replay's verdict on each, and every game,
                     decided or open, flowing on into the race model
                     (output/replay_summary.csv, output/race_calibration.csv)
  dg3_race_step      one step of the race model on the same game: the
                     possession scoring shares, the five states one
                     possession can lead to, and the exact chance each team
                     gets there first (output/ppp_distributions.csv,
                     output/race_games.csv)

The example game is chosen by rule, not by hand: among NBA regular-season
games whose winner changes under the replay, with the target reached in
regulation and no overtime, the one whose target was reached latest.

Run:  python python/09_diagrams.py          (writes figures/dg*.svg)
      python python/09_diagrams.py --check  (fails if a committed SVG
                                             differs from a fresh build)
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "basketball-analysis-tools"))
import famdiagram as fd  # noqa: E402

OUT = ROOT / "output"
FIG = ROOT / "figures"
GAMELOGS = ROOT.parent / "playoff-series-study" / "data" / "raw" / "gamelogs"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPLAY = _load("python/02_replay.py", "elam_replay_rules")
RACE = _load("python/05_race_model.py", "elam_race_rules")


def pct(p: float, nd: int = 1) -> str:
    return f"{p * 100:.{nd}f}%"


def clock(secs: float) -> str:
    whole = int(secs)
    s = f"{whole // 60}:{whole % 60:02d}"
    return s if secs == whole else f"{s}.{round((secs - whole) * 10):d}"


def n(x: int) -> str:
    return f"{x:,}"


# ---------------------------------------------------------------------------
# The example game
# ---------------------------------------------------------------------------

def example_game() -> dict:
    rep = pl.read_csv(OUT / "replay_games.csv", schema_overrides={"gameId": pl.Utf8})
    race = pl.read_csv(OUT / "race_games.csv", schema_overrides={"gameId": pl.Utf8}).select(
        "gameId", "ball", "p_home_league", "home_team_id", "away_team_id")
    pick = (rep.filter(pl.col("flipped") & (pl.col("league") == "nba")
                       & (pl.col("season_type") == "regular")
                       & pl.col("reach_in_regulation") & ~pl.col("overtime"))
            .sort(["reach_secs_left", "gameId"]).head(1)
            .join(race, on="gameId"))
    g = pick.row(0, named=True)
    logs = pl.concat([pl.read_csv(p, schema_overrides={"GAME_ID": pl.Utf8},
                                  infer_schema_length=0)
                      for p in sorted(GAMELOGS.glob("nba_*_rs.csv"))], how="diagonal")
    rows = logs.filter(pl.col("GAME_ID") == g["gameId"])
    team = {int(r["TEAM_ID"]): r for r in rows.iter_rows(named=True)}
    home, away = team[g["home_team_id"]], team[g["away_team_id"]]
    d = date.fromisoformat(home["GAME_DATE"][:10])
    g["when"] = f"{d:%B} {d.day}, {d.year}"
    g["home_abbr"], g["away_abbr"] = home["TEAM_ABBREVIATION"], away["TEAM_ABBREVIATION"]
    g["home_name"], g["away_name"] = home["TEAM_NAME"], away["TEAM_NAME"]
    # Finals in the gamelog must equal the committed ones (the study's own check).
    assert int(home["PTS"]) == g["final_home"] and int(away["PTS"]) == g["final_away"]
    lead_home = g["trigger_leader"] == "home"
    g["lead_abbr"] = g["home_abbr"] if lead_home else g["away_abbr"]
    g["trail_abbr"] = g["away_abbr"] if lead_home else g["home_abbr"]
    g["lead_trig"] = g["trigger_h"] if lead_home else g["trigger_a"]
    g["trail_trig"] = g["trigger_a"] if lead_home else g["trigger_h"]
    g["p_lead"] = g["p_home_league"] if lead_home else 1 - g["p_home_league"]
    return g


# ---------------------------------------------------------------------------
# 1. The rule on one game
# ---------------------------------------------------------------------------

def card(d, x, y, w, head, sub, rows, win, s, note, note_fill):
    """A scoreboard snapshot: header, two team rows, a result line."""
    rh = s + 16
    h = 2 * rh + 16
    d.text(x, y - s - 14, head, size=s + 1, weight="600")
    d.text(x, y - 8, sub, size=s, fill="ink3")
    d.rect(x, y, w, h, fill="surface", stroke="rule", sw=1, rx=6)
    for i, (abbr, pts) in enumerate(rows):
        ry = y + 8 + i * rh
        if abbr == win:
            d.rect(x + 4, ry, w - 8, rh, fill=note_fill, opacity=0.14, rx=4)
        d.text(x + 14, ry + rh - 8, abbr, size=s + 2, weight="600",
               fill="ink" if abbr == win else "ink2")
        d.text(x + w - 14, ry + rh - 8, str(pts), size=s + 4, anchor="end", display=True,
               fill="ink" if abbr == win else "ink2")
    d.text(x, y + h + s + 8, note, size=s, fill=note_fill, weight="600")
    return h


def dg_game(layout: str) -> fd.Diagram:
    g = example_game()
    away, home = g["away_abbr"], g["home_abbr"]
    elam_win = home if g["elam_winner"] == "home" else away
    real_win = home if g["actual_winner"] == "home" else away
    title = (f"{g['away_name']} at {g['home_name']}, {g['when']}: the Elam rule read on "
             f"the real play-by-play")
    trig_mins = int(REPLAY.TRIGGER_SECS // 60)
    snaps = [
        (f"Trigger, {clock(g['trigger_secs_left'])} left",
         f"first dead ball under {trig_mins}:00",
         [(away, g["trigger_a"]), (home, g["trigger_h"])], None,
         f"Target: {g['lead_trig']} + {REPLAY.TARGET_MARGIN} = {g['target']}", "ink"),
        (f"Elam ends, {clock(g['reach_secs_left'])} left",
         f"{elam_win} reaches {g['target']} first",
         [(away, g["reach_a"]), (home, g["reach_h"])], elam_win,
         f"Elam winner: {elam_win}", "accent"),
        ("Real buzzer, 0:00", "the clock runs out",
         [(away, g["final_away"]), (home, g["final_home"])], real_win,
         f"Real winner: {real_win}", "c8"),
    ]
    arrows = [f"race to {g['target']}", "clock runs on"]
    if layout == "wide":
        W, H, s = 760, 262, 14
        d = fd.Diagram(W, H, title)
        d.text(24, 26, f"{g['away_name']} at {g['home_name']}, {g['when']}",
               size=s + 3, weight="600")
        cw, gap, y = 180, 96, 104
        for i, (head, sub, rows, win, note, nf) in enumerate(snaps):
            x = 24 + i * (cw + gap)
            h = card(d, x, y, cw, head, sub, rows, win, s, note, nf)
            if i < 2:
                ax = x + cw + 8
                d.line(ax, y + h / 2, ax + gap - 16, y + h / 2, stroke="ink3", sw=1.6,
                       arrow=True)
                d.text(ax + (gap - 16) / 2, y + h / 2 - 10, arrows[i].split()[0], size=s,
                       fill="ink3", anchor="middle")
                d.text(ax + (gap - 16) / 2, y + h / 2 + 22, " ".join(arrows[i].split()[1:]),
                       size=s, fill="ink3", anchor="middle")
        d.text(24, H - 16, f"Under the rule the game ends the moment a team reaches "
               f"{g['target']}; the {g['reach_secs_left']:g} seconds after it never happen.",
               size=s, fill="ink3")
    else:
        W, s = 360, 13
        cw, y0, step = 240, 108, 150
        H = y0 + 3 * step + 10
        d = fd.Diagram(W, H, title)
        d.text(16, 24, f"{g['away_name']} at", size=s + 2, weight="600")
        d.text(16, 44, f"{g['home_name']}, {g['when']}", size=s + 2, weight="600")
        for i, (head, sub, rows, win, note, nf) in enumerate(snaps):
            x, y = 16, y0 + i * step
            h = card(d, x, y, cw, head, sub, rows, win, s, note, nf)
            if i < 2:
                ax = x + cw + 22
                d.line(ax, y + 10, ax, y + step - 30, stroke="ink3", sw=1.6, arrow=True)
                words = arrows[i].split()
                lines = [" ".join(words[:2]), " ".join(words[2:])]
                for j, word in enumerate(lines):
                    d.text(ax + 10, y + 40 + j * (s + 4), word, size=s, fill="ink3")
        d.text(16, H - 30, f"The game ends the moment a team reaches", size=s, fill="ink3")
        d.text(16, H - 12, f"{g['target']}; the {g['reach_secs_left']:g} seconds after it "
               f"never happen.", size=s, fill="ink3")
    return d


# ---------------------------------------------------------------------------
# 2. How the three answers fit together
# ---------------------------------------------------------------------------

def band(d, a0, a1, b0, b1, u0, u1, horizontal, fill, opacity):
    """A Sankey band from span (a0, a1) at flow position u0 to span (b0, b1)
    at u1. Horizontal: u is x and the spans are y; otherwise the reverse."""
    m = (u0 + u1) / 2
    pt = (lambda u, v: f"{u:.1f},{v:.1f}") if horizontal else (lambda u, v: f"{v:.1f},{u:.1f}")
    d.path(f"M{pt(u0, a0)} C{pt(m, a0)} {pt(m, b0)} {pt(u1, b0)} L{pt(u1, b1)} "
           f"C{pt(m, b1)} {pt(m, a1)} {pt(u0, a1)} Z", fill=fill, stroke=None,
           opacity=opacity)


def node(d, u, v0, v1, thick, horizontal, fill):
    if horizontal:
        d.rect(u, v0, thick, v1 - v0, fill=fill)
    else:
        d.rect(v0, u, v1 - v0, thick, fill=fill)


def dg_tiers(layout: str) -> fd.Diagram:
    """A Sankey of the NBA regular season's games through the tiers: all
    games split by the replay's verdict, and every game, decided or open,
    flowing on into the race model."""
    rs = pl.read_csv(OUT / "replay_summary.csv").filter(
        (pl.col("league") == "nba") & (pl.col("season") == "pooled")
        & (pl.col("season_type") == "regular")).row(0, named=True)
    cal = pl.read_csv(OUT / "race_calibration.csv").filter(
        (pl.col("version") == "league") & (pl.col("bin") == "all")).row(0, named=True)
    games, flipped, unres = rs["games"], rs["flipped"], rs["unresolved"]
    same = games - flipped - unres
    trig = int(REPLAY.TRIGGER_SECS // 60)
    title = (f"How {n(games)} NBA regular-season games flow through the study: the replay "
             f"decides {n(same + flipped)} and leaves {n(unres)} open, and the race model "
             f"gives every game a chance")
    cats = [(same, "nba", 0.5, f"{n(same)} same winner"),
            (flipped, "c8", 0.9, f"{n(flipped)} winner changes"),
            (unres, "ink3", 0.45, f"{n(unres)} left open")]
    wide = layout == "wide"
    if wide:
        W, H, s = 760, 420, 14
        horizontal, thick, span, gap = True, 14, 230, 16
        u = [24, 300, 560]
        v_top = 108
    else:
        W, H, s = 360, 520, 12
        horizontal, thick, span, gap = False, 12, 300, 14
        u = [96, 236, 386]
        v_top = 30
    d = fd.Diagram(W, H, title)
    mid_total = span + gap * (len(cats) - 1)
    v_mid0 = v_top + (span - mid_total) / 2
    # left node, middle nodes, right node
    node(d, u[0], v_top, v_top + span, thick, horizontal, "ink2")
    node(d, u[2], v_top, v_top + span, thick, horizontal, "accent")
    a = v_top
    m = v_mid0
    spans = []
    for cnt, col, op, lab in cats:
        h = span * cnt / games
        band(d, a, a + h, m, m + h, u[0] + thick, u[1], horizontal, col, op * 0.6)
        node(d, u[1], m, m + h, thick, horizontal, col)
        spans.append((a, m, h))
        a += h
        m += h + gap
    for (a, m, h), (cnt, col, op, lab) in zip(spans, cats):
        band(d, m, m + h, a, a + h, u[1] + thick, u[2], horizontal, col, op * 0.35)
    lab_fill = {"nba": "nba", "c8": "c8", "ink3": "ink2"}
    if wide:
        d.text(24, 24, f"{n(games)} NBA regular-season games, 2023-24 to 2025-26",
               size=s + 2, weight="600")
        d.text(24, 46, f"Trigger: first dead ball under {trig}:00 of Q4. Target: leading "
               f"score + {REPLAY.TARGET_MARGIN}.", size=s, fill="ink2")
        for x, head in ((u[0], "All games"), (u[1], "1  Literal replay"),
                        (u[2], "2  Race model")):
            d.text(x, 86, head, size=s + 1, weight="600")
        for (a, m, h), (cnt, col, op, lab) in zip(spans, cats):
            d.text(u[1] + thick + 8, m + h / 2 + 5, lab, size=s, fill=lab_fill[col],
                   weight="600")
        d.text(u[1] + thick + 8, spans[0][1] + spans[0][2] / 2 + 24, "decided at the target",
               size=s, fill="ink3")
        d.text(u[1] + thick + 8, spans[2][1] + spans[2][2] / 2 + 24,
               "no team reaches it", size=s, fill="ink3")
        rx = u[2] + thick + 10
        for j, line in enumerate(["a chance for", f"all {n(games)} games,",
                                  "open or decided", "", f"checked first on",
                                  f"{n(cal['races'])} real races", "inside games"]):
            if line:
                d.text(rx, v_top + 18 + j * (s + 6), line, size=s,
                       fill="ink" if j < 3 else "ink3", weight="600" if j < 3 else None)
        d.text(24, H - 30, "3  Endgame audit, alongside: overtime, take fouls, free throws, "
               "and real minutes", size=s, fill="ink2")
        d.text(24, H - 12, "after the trigger, the parts of a real ending the rule would "
               "remove.", size=s, fill="ink2")
    else:
        d.text(16, 30, f"{n(games)} NBA regular-season games", size=s + 1, weight="600")
        d.text(16, 48, f"trigger under {trig}:00 of Q4, target lead + "
               f"{REPLAY.TARGET_MARGIN}", size=s, fill="ink2")
        d.text(16, 76, "1  Literal replay splits them:", size=s + 1, weight="600")
        (a0, m0, h0), (a1, m1, h1), (a2, m2, h2) = spans
        d.text(m0 + 4, u[1] - 26, cats[0][3], size=s, fill="nba", weight="600")
        d.text(m1 + h1 / 2, u[1] - 8, cats[1][3], size=s, fill="c8", weight="600",
               anchor="middle")
        d.text(m2 + h2 - 4, u[1] - 26, cats[2][3], size=s, fill="ink2", weight="600",
               anchor="end")
        d.text(16, u[1] + 54, "2  Race model: a chance for", size=s + 1, weight="600")
        d.text(16, u[1] + 72, f"all {n(games)} games, open or decided", size=s + 1,
               weight="600")
        d.text(16, u[2] + thick + 22, f"Checked first on {n(cal['races'])} real races",
               size=s, fill="ink3")
        d.text(16, u[2] + thick + 40, "inside games.", size=s, fill="ink3")
        d.text(16, H - 46, "3  Endgame audit, alongside: overtime,", size=s, fill="ink2")
        d.text(16, H - 28, "take fouls, free throws, and real minutes", size=s,
               fill="ink2")
        d.text(16, H - 10, "after the trigger.", size=s, fill="ink2")
    return d


# ---------------------------------------------------------------------------
# 3. One step of the race model
# ---------------------------------------------------------------------------

def dg_step(layout: str) -> fd.Diagram:
    g = example_game()
    dist = pl.read_csv(OUT / "ppp_distributions.csv").filter(
        (pl.col("scope") == "league") & (pl.col("league") == g["league"])
        & (pl.col("season") == g["season"])).row(0, named=True)
    p = [dist[f"p{k}"] for k in range(RACE.K)]
    ball_home = g["ball"] == "h"
    ball = g["home_abbr"] if ball_home else g["away_abbr"]
    other = g["away_abbr"] if ball_home else g["home_abbr"]
    need = {g["home_abbr"]: g["target"] - g["trigger_h"],
            g["away_abbr"]: g["target"] - g["trigger_a"]}
    lead, trail = g["lead_abbr"], g["trail_abbr"]
    title = (f"One step of the race model from the {g['when']} trigger: {trail} needs "
             f"{need[trail]}, {lead} needs {need[lead]}; {lead} reaches {g['target']} first "
             f"{pct(g['p_lead'])} of the time")
    klabel = [str(k) for k in range(RACE.K - 1)] + [f"{RACE.K - 1}+"]
    outcomes = []
    for k in range(RACE.K):
        if k == 0:
            outcomes.append((p[k], f"{klabel[k]}: ball to {other}, nothing changes"))
        else:
            outcomes.append((p[k], f"{klabel[k]}: {ball} needs {need[ball] - k}, ball to "
                                   f"{other}"))
    result = [(lead, g["p_lead"], "accent"), (trail, 1 - g["p_lead"], "c8")]
    head1 = f"Points on one possession, {g['league'].upper()} {g['season']}"
    sub1 = "no clock play: Q1 to Q3 and early Q4"
    state = f"{trail} {need[trail]} to go, {lead} {need[lead]} to go, {ball} ball"
    if layout == "wide":
        W, H, s = 760, 380, 14
        d = fd.Diagram(W, H, title)
        d.text(24, 26, head1, size=s + 1, weight="600")
        d.text(24, 46, sub1, size=s, fill="ink3")
        bx, by, bw, bh = 64, 66, 170, 30
        for k, pk in enumerate(p):
            y = by + k * (bh + 8)
            d.text(bx - 10, y + bh / 2 + 5, klabel[k], size=s, fill="ink2", anchor="end")
            d.rect(bx, y, bw, bh, fill="surface2")
            d.rect(bx, y, max(bw * pk, 1.5), bh, fill="nba", opacity=0.85)
            d.text(bx + max(bw * pk, 1.5) + 6, y + bh / 2 + 5, pct(pk), size=s,
                   fill="ink")
        d.text(bx - 10, by + 5 * (bh + 8) + 14, "points", size=s, fill="ink3")
        # the state and its five successors
        sx, sy = 330, 26
        d.text(sx, sy, "From the trigger state", size=s + 1, weight="600")
        d.rect(sx, sy + 12, 400, 34, fill="surface2", stroke="rule", sw=1, rx=6)
        d.text(sx + 12, sy + 34, state, size=s, weight="600")
        for k, (pk, lab) in enumerate(outcomes):
            y = by + k * (bh + 8) + bh / 2
            d.path(f"M{sx + 20},{sy + 46} C{sx + 20},{y} {sx + 30},{y} {sx + 44},{y}",
                   stroke="ink3", sw=1.2, arrow=True)
            d.text(sx + 52, y + 5, lab, size=s, fill="ink2")
        ry = by + 5 * (bh + 8) + 14
        d.text(24, ry + 18, f"Repeat from every new state until one team's need reaches "
               f"zero. Solved exactly (no simulation):", size=s, fill="ink2")
        for i, (abbr, pr, col) in enumerate(result):
            x = 24 + i * 240
            d.rect(x, ry + 34, 220, 46, fill=col, opacity=0.14, rx=6)
            d.text(x + 12, ry + 63, f"{abbr} first", size=s + 1, weight="600", fill=col)
            d.text(x + 208, ry + 66, pct(pr), size=s + 8, anchor="end", display=True,
                   fill=col)
        d.text(504, ry + 56, f"Real replay: {lead}", size=s, fill="ink3")
        d.text(504, ry + 74, f"reached {g['target']} first", size=s, fill="ink3")
    else:
        W, s = 360, 13
        H = 620
        d = fd.Diagram(W, H, title)
        d.text(16, 24, head1, size=s + 1, weight="600")
        d.text(16, 42, sub1, size=s, fill="ink3")
        bx, by, bw, bh = 52, 58, 200, 24
        for k, pk in enumerate(p):
            y = by + k * (bh + 6)
            d.text(bx - 8, y + bh / 2 + 5, klabel[k], size=s, fill="ink2", anchor="end")
            d.rect(bx, y, bw, bh, fill="surface2")
            d.rect(bx, y, max(bw * pk, 1.5), bh, fill="nba", opacity=0.85)
            d.text(bx + max(bw * pk, 1.5) + 6, y + bh / 2 + 5, pct(pk), size=s)
        sy = by + 5 * (bh + 6) + 30
        d.text(16, sy, "From the trigger state", size=s + 1, weight="600")
        d.rect(16, sy + 10, W - 32, 50, fill="surface2", stroke="rule", sw=1, rx=6)
        d.text(28, sy + 30, f"{trail} {need[trail]} to go, {lead} {need[lead]} to go,",
               size=s, weight="600")
        d.text(28, sy + 49, f"{ball} has the ball", size=s, weight="600")
        oy = sy + 86
        for k, (pk, lab) in enumerate(outcomes):
            y = oy + k * 26
            d.path(f"M28,{sy + 60} C28,{y - 5} 30,{y - 5} 40,{y - 5}", stroke="ink3", sw=1.2,
                   arrow=True)
            d.text(46, y, lab.split(", ball to")[0].replace("nothing changes",
                                                             "no change"),
                   size=s, fill="ink2")
        d.text(16, oy + 5 * 26, f"After any score, the ball goes to {other}.", size=s,
               fill="ink3")
        ry = oy + 6 * 26 + 8
        d.text(16, ry, "Repeat until one team's need reaches", size=s, fill="ink2")
        d.text(16, ry + 18, "zero. Solved exactly (no simulation):", size=s, fill="ink2")
        for i, (abbr, pr, col) in enumerate(result):
            x = 16 + i * 168
            d.rect(x, ry + 32, 160, 46, fill=col, opacity=0.14, rx=6)
            d.text(x + 10, ry + 61, f"{abbr} first", size=s, weight="600", fill=col)
            d.text(x + 150, ry + 64, pct(pr), size=s + 7, anchor="end", display=True,
                   fill=col)
        d.text(16, ry + 104, f"Real replay: {lead} reached {g['target']} first",
               size=s, fill="ink3")
    return d


BUILDERS = {"dg1_one_game": dg_game, "dg2_three_answers": dg_tiers,
            "dg3_race_step": dg_step}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    fails = []
    for ref, build in BUILDERS.items():
        wide, narrow = build("wide"), build("narrow")
        if args.check:
            for dg, name in ((wide, f"{ref}.svg"), (narrow, f"{ref}_narrow.svg")):
                p = FIG / name
                if not p.exists() or p.read_text() != dg.svg():
                    fails.append(name)
        else:
            for p in fd.save(FIG, ref, wide, narrow):
                print("wrote", p.relative_to(ROOT))
    if args.check:
        for f in fails:
            print("FAIL", f, "differs from a fresh build")
        print("DIAGRAMS", "FAILED" if fails else f"PASSED: {len(BUILDERS)} diagrams")
        return 1 if fails else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
