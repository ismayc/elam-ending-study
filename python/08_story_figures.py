"""Build the interactive figures for the family page (docs/story.md).

Every value comes from committed, R-reconciled outputs (replay_by_margin.csv,
race_by_margin.csv, race_calibration.csv, endgame_by_margin.csv,
endgame_summary.csv). Figures are plotly originals written to figures/;
report_builder.py swaps in the family's famplot engine at publish time, so
only traces famplot draws are used (scatter lines and markers, error bars,
horizontal reference lines).

Figures:
  fig1_replay_margin_py   tier 1: share of games whose winner changes, by trigger margin
  fig2_leader_margin_py   tier 2: leader's win rate, clock (real) against Elam (model)
  fig3_calibration_py     tier 2: predicted against observed on mid-game races
  fig4_minutes_margin_py  tier 3: real minutes for the last 2:00, by margin at 2:00

Run:  python python/08_story_figures.py
"""
from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIG = ROOT / "figures"
LEAGUES = {"nba": "NBA", "wnba": "WNBA"}
# famplot's first two family colors, so each league keeps its color.
COLORS = {"nba": "#2a78d6", "wnba": "#eb6834"}
LIGHT = {"nba": "#8db8ea", "wnba": "#f3a77f"}
GREY = "#898781"


def base_layout(title: str, xtitle: str, ytitle: str, height: int = 420) -> dict:
    return dict(title=title, xaxis_title=xtitle, yaxis_title=ytitle, template="plotly_white",
                height=height, margin=dict(l=70, r=30, t=60, b=60),
                legend=dict(orientation="h", y=-0.2))


def fig_replay(m: pl.DataFrame) -> go.Figure:
    f = go.Figure()
    for lg, name in LEAGUES.items():
        rows = m.filter(pl.col("league") == lg)
        f.add_trace(go.Scatter(
            x=rows["margin"].to_list(), y=(rows["flip_rate"] * 100).to_list(),
            mode="lines+markers", name=name, line=dict(color=COLORS[lg]),
            marker=dict(size=8, color=COLORS[lg]),
            customdata=list(zip(rows["flipped"].to_list(), rows["games"].to_list())),
            hovertemplate=f"{name}, margin %{{x}}: %{{y:.1f}}% "
                          f"(%{{customdata[0]}} of %{{customdata[1]}} games)<extra></extra>"))
    f.update_layout(**base_layout("Literal replay: games whose winner changes under Elam",
                                  "Margin at the trigger (points; 0 is tied)",
                                  "Share of games (%)"))
    f.update_xaxes(type="category")
    return f


def fig_leader(m: pl.DataFrame) -> go.Figure:
    f = go.Figure()
    for lg, name in LEAGUES.items():
        rows = m.filter(pl.col("league") == lg)
        f.add_trace(go.Scatter(
            x=rows["margin"].to_list(), y=(rows["clock"] * 100).to_list(), mode="markers",
            name=f"{name}, real games (clock)",
            marker=dict(size=9, color=COLORS[lg]),
            error_y=dict(type="data", symmetric=False,
                         array=((rows["clock_hi"] - rows["clock"]) * 100).to_list(),
                         arrayminus=((rows["clock"] - rows["clock_lo"]) * 100).to_list()),
            customdata=[[g] for g in rows["games"].to_list()],
            hovertemplate=f"{name} real, margin %{{x}}: %{{y:.1f}}% "
                          f"(%{{customdata[0]}} games)<extra></extra>"))
        f.add_trace(go.Scatter(
            x=rows["margin"].to_list(), y=(rows["elam_league"] * 100).to_list(), mode="lines",
            name=f"{name}, Elam (model)", line=dict(color=LIGHT[lg], width=2),
            hovertemplate=f"{name} Elam model, margin %{{x}}: %{{y:.1f}}%<extra></extra>"))
    f.update_layout(**base_layout("How often the team ahead at the trigger wins",
                                  "Margin at the trigger (points)",
                                  "Leader wins (%, real games with 95% interval)", height=460))
    f.update_xaxes(type="category")
    return f


def fig_calibration(cal: pl.DataFrame) -> go.Figure:
    rows = cal.filter((pl.col("version") == "league")
                      & ~pl.col("bin").is_in(["all", "brier"])).sort("mean_predicted")
    f = go.Figure()
    f.add_trace(go.Scatter(x=[50, 100], y=[50, 100], mode="lines", name="Perfect calibration",
                           line=dict(color=GREY, dash="dash", width=1), hoverinfo="skip"))
    f.add_trace(go.Scatter(
        x=(rows["mean_predicted"] * 100).to_list(), y=(rows["observed"] * 100).to_list(),
        mode="lines+markers", name="Model, mid-game races", line=dict(color=COLORS["nba"]),
        marker=dict(size=9, color=COLORS["nba"]),
        customdata=[[r] for r in rows["races"].to_list()],
        hovertemplate="Predicted %{x:.1f}%, observed %{y:.1f}% "
                      "(%{customdata[0]} races)<extra></extra>"))
    f.update_layout(**base_layout("The race model on real races inside games",
                                  "Predicted chance the favorite reaches leader + 8 first (%)",
                                  "Observed (%)"))
    return f


def fig_minutes(m: pl.DataFrame, summ: pl.DataFrame) -> go.Figure:
    f = go.Figure()
    for lg, name in LEAGUES.items():
        rows = m.filter(pl.col("league") == lg)
        f.add_trace(go.Scatter(
            x=rows["margin"].to_list(), y=rows["median_real_min"].to_list(),
            mode="lines+markers", name=name, line=dict(color=COLORS[lg]),
            marker=dict(size=9, color=COLORS[lg]),
            customdata=[[g] for g in rows["games"].to_list()],
            hovertemplate=f"{name}, margin %{{x}}: %{{y:.1f}} real minutes "
                          f"(median of %{{customdata[0]}} games)<extra></extra>"))
    q3 = summ.filter((pl.col("league") == "nba") & (pl.col("season") == "pooled")
                     & (pl.col("season_type") == "all"))["median_real_min_q3_mid2"].item()
    f.add_hline(y=q3, line_width=1, line_dash="dash", line_color=GREY)
    f.add_hline(y=2, line_width=1, line_color=GREY)
    f.update_layout(**base_layout("Real minutes for the last two minutes of the fourth quarter",
                                  "Margin with 2:00 left (points)", "Median real minutes"))
    f.update_xaxes(type="category")
    return f


def main() -> None:
    FIG.mkdir(exist_ok=True)
    figs = {
        "fig1_replay_margin_py": fig_replay(pl.read_csv(OUT / "replay_by_margin.csv",
                                                        schema_overrides={"margin": pl.Utf8})),
        "fig2_leader_margin_py": fig_leader(pl.read_csv(OUT / "race_by_margin.csv",
                                                        schema_overrides={"margin": pl.Utf8})),
        "fig3_calibration_py": fig_calibration(pl.read_csv(OUT / "race_calibration.csv")),
        "fig4_minutes_margin_py": fig_minutes(pl.read_csv(OUT / "endgame_by_margin.csv",
                                                          schema_overrides={"margin": pl.Utf8}),
                                              pl.read_csv(OUT / "endgame_summary.csv")),
    }
    for name, fig in figs.items():
        fig.write_html(FIG / f"{name}.html", include_plotlyjs="cdn")
        print("wrote", f"figures/{name}.html")


if __name__ == "__main__":
    main()
