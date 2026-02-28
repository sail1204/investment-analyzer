"""
Investment Analyzer — NiceGUI Dashboard

Pages:
  /                 Weekly summary table (all stocks, clickable rows)
  /stock/{ticker}   Stock detail card (price chart, thesis, fundamentals)
  /corrections      Self-correction log
  /accuracy         Accuracy tracker (builds up after 4+ weeks)
"""

import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
from nicegui import ui

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import (
    get_all_corrections,
    get_all_snapshots_for_run,
    get_available_run_dates,
    get_ticker_history,
    init_db,
)

init_db()

# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt(val, suffix: str = "", default: str = "—", decimals: int = 1) -> str:
    if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return default


def get_latest_run_date() -> Optional[str]:
    dates = get_available_run_dates()
    return dates[0] if dates else None


# Simple in-process price cache (refreshes on server restart)
_price_cache: dict[str, pd.DataFrame] = {}


def fetch_price_history(ticker: str) -> pd.DataFrame:
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        import yfinance as yf
        data = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            _price_cache[ticker] = pd.DataFrame()
            return pd.DataFrame()
        data = data.reset_index()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        result = data[["Date", "Close"]].dropna()
        _price_cache[ticker] = result
        return result
    except Exception:
        _price_cache[ticker] = pd.DataFrame()
        return pd.DataFrame()


# ── Pill badge HTML ────────────────────────────────────────────────────────────

SIGNAL_STYLE = {
    "Cheap":     "background:#dcfce7;color:#15803d",
    "Fair":      "background:#f1f5f9;color:#475569",
    "Expensive": "background:#fee2e2;color:#b91c1c",
}
DRIFT_STYLE = {
    "Stable":       "background:#dcfce7;color:#15803d",
    "Updated":      "background:#fef3c7;color:#b45309",
    "Contradicted": "background:#fee2e2;color:#b91c1c",
    "New":          "background:#e0f2fe;color:#0369a1",
}
PILL_BASE = (
    "display:inline-block;padding:2px 10px;border-radius:999px;"
    "font-size:0.78em;font-weight:700;letter-spacing:0.03em;"
)


def pill(text: str, style_map: dict) -> str:
    style = style_map.get(text, "background:#f1f5f9;color:#475569")
    return f'<span style="{PILL_BASE}{style}">{text}</span>'


# ── Shared header with navigation ──────────────────────────────────────────────

def add_header():
    with ui.header().classes("bg-indigo-600 text-white px-6 flex items-center gap-6 shadow-md"):
        ui.label("📈 Investment Analyzer").classes("text-xl font-bold py-3")
        ui.space()
        ui.link("Summary",        "/").classes("text-white/80 hover:text-white text-sm font-medium py-3")
        ui.link("Correction Log", "/corrections").classes("text-white/80 hover:text-white text-sm font-medium py-3")
        ui.link("Accuracy",       "/accuracy").classes("text-white/80 hover:text-white text-sm font-medium py-3")


def page_wrap(content_fn):
    """Add header then render the page body inside a padded container."""
    add_header()
    with ui.element("div").classes("px-6 py-4 max-w-screen-2xl mx-auto w-full"):
        content_fn()


# ── Page 1: Weekly Summary ─────────────────────────────────────────────────────

@ui.page("/")
def summary_page():
    def body():
        run_date = get_latest_run_date()
        if not run_date:
            ui.label("No data yet — run the weekly agent first.").classes("text-gray-400 mt-8")
            return

        rows_raw = get_all_snapshots_for_run(run_date)
        if not rows_raw:
            ui.label(f"No snapshots found for week {run_date}.").classes("text-gray-400 mt-8")
            return

        # Build latest drift per ticker
        corrections = get_all_corrections() or []
        drift_map: dict[str, str] = {}
        if corrections:
            corr_df = pd.DataFrame(corrections).sort_values("run_date")
            drift_map = corr_df.groupby("ticker")["drift_signal"].last().to_dict()

        with ui.row().classes("items-baseline gap-3 mb-1"):
            ui.label("Weekly Summary").classes("text-2xl font-bold")
            ui.badge(f"Week {run_date}").props("color=indigo outline")

        ui.label(
            f"{len(rows_raw)} stocks · click a ticker to open stock detail"
        ).classes("text-sm text-gray-400 mb-4")

        # Build AG Grid row data
        grid_rows = []
        for r in rows_raw:
            t = r.get("ticker", "")
            chg = r.get("price_change_1w")
            grid_rows.append({
                "ticker":      t,
                "company":     r.get("company_name") or "",
                "sector":      r.get("sector") or "",
                "signal":      r.get("valuation_signal") or "—",
                "conviction":  r.get("conviction") or 0,
                "price":       fmt(r.get("price"), "$", decimals=2),
                "change_1w":   (f"{chg:+.1f}%" if chg is not None else "—"),
                "pe":          fmt(r.get("pe_ratio"), "x"),
                "ev_ebitda":   fmt(r.get("ev_ebitda"), "x"),
                "fcf_yield":   fmt(r.get("fcf_yield"), "%"),
                "value_score": fmt(r.get("value_score")),
                "drift":       drift_map.get(t, "New"),
            })

        col_def = {"sortable": True, "filter": True, "resizable": True}
        # Ticker column uses a cellRenderer to produce a plain <a> link —
        # no Python event wiring needed, browser navigates directly.
        ticker_renderer = (
            "function(p) {"
            "  return '<a href=\"/stock/' + p.value + '\" "
            "style=\"color:#4f46e5;font-weight:700;text-decoration:none\">' + p.value + '</a>';"
            "}"
        )
        columns = [
            {"headerName": "Ticker",      "field": "ticker",      "width": 100,
             "pinned": "left", "cellRenderer": ticker_renderer},
            {"headerName": "Company",     "field": "company",     "width": 210},
            {"headerName": "Sector",      "field": "sector",      "width": 175},
            {"headerName": "Signal",      "field": "signal",      "width": 100},
            {"headerName": "Conv.",       "field": "conviction",  "width": 75, "type": "numericColumn"},
            {"headerName": "Price",       "field": "price",       "width": 90},
            {"headerName": "1W Δ",        "field": "change_1w",   "width": 90},
            {"headerName": "P/E",         "field": "pe",          "width": 80},
            {"headerName": "EV/EBITDA",   "field": "ev_ebitda",   "width": 105},
            {"headerName": "FCF Yield",   "field": "fcf_yield",   "width": 100},
            {"headerName": "Value Score", "field": "value_score", "width": 110, "type": "numericColumn"},
            {"headerName": "Drift",       "field": "drift",       "width": 115},
        ]

        ui.aggrid({
            "columnDefs":    columns,
            "rowData":       grid_rows,
            "defaultColDef": col_def,
            "domLayout":     "autoHeight",
        }).classes("w-full")

    page_wrap(body)


# ── Page 2: Stock Detail ───────────────────────────────────────────────────────

@ui.page("/stock/{ticker}")
def stock_detail_page(ticker: str):
    def body():
        run_date = get_latest_run_date()
        if not run_date:
            ui.label("No data found.").classes("text-gray-400")
            return

        rows = get_all_snapshots_for_run(run_date)
        row = next((r for r in rows if r.get("ticker") == ticker), None)
        if not row:
            ui.label(f"No snapshot found for {ticker} in week {run_date}.").classes("text-gray-400")
            return

        corrections = get_all_corrections() or []
        ticker_corrections = sorted(
            [c for c in corrections if c.get("ticker") == ticker],
            key=lambda c: c.get("run_date", ""),
            reverse=True,
        )
        latest_corr = ticker_corrections[0] if ticker_corrections else None

        signal     = row.get("valuation_signal") or "Fair"
        drift      = latest_corr["drift_signal"] if latest_corr else "New"
        conviction = int(row.get("conviction") or 0)

        # ── Back button + title ────────────────────────────────────────────────
        ui.button("← Back", on_click=lambda: ui.navigate.to("/")).props("flat").classes(
            "text-indigo-600 mb-3 -ml-2"
        )

        ui.html(
            f"<h2 style='font-size:1.6rem;font-weight:700;margin-bottom:4px'>"
            f"{ticker}&nbsp;"
            f"<span style='font-size:1rem;font-weight:400;color:#6b7280'>"
            f"{row.get('company_name','')}</span></h2>"
        )
        ui.html(
            f"<div style='display:flex;gap:8px;align-items:center;margin-bottom:20px'>"
            f"{pill(signal, SIGNAL_STYLE)}"
            f"{pill(drift, DRIFT_STYLE)}"
            f"<span style='color:#6b7280;font-size:0.88em'>"
            f"{row.get('sector','—')} · {row.get('gics_sub_industry','')}</span>"
            f"</div>"
        )

        # ── KPI strip ─────────────────────────────────────────────────────────
        price_chg = row.get("price_change_1w")
        chg_color = "#22c55e" if (price_chg or 0) >= 0 else "#ef4444"
        chg_str   = f"{price_chg:+.1f}%" if price_chg is not None else "—"

        with ui.row().classes("gap-4 mb-2 flex-wrap"):
            for label, value, extra_color in [
                ("Price",        f"${fmt(row.get('price'), decimals=2)}", None),
                ("1W Change",    chg_str,                                 chg_color),
                ("Conviction",   f"{conviction}/10",                      None),
                ("Weeks Held",   str(row.get("thesis_age_weeks", 1)),     None),
                ("Value Score",  f"{fmt(row.get('value_score'))}/100",    None),
            ]:
                with ui.card().classes("px-5 py-3 min-w-[110px]"):
                    ui.label(label).classes("text-xs text-gray-400 mb-1")
                    color_style = f"color:{extra_color};" if extra_color else ""
                    ui.html(
                        f"<span style='font-size:1.25rem;font-weight:700;{color_style}'>{value}</span>"
                    )

        # Conviction progress bar
        ui.linear_progress(conviction / 10).props("color=indigo").classes("w-full mb-4")

        # ── 1-Year price chart ─────────────────────────────────────────────────
        price_hist = fetch_price_history(ticker)
        if not price_hist.empty:
            fig = px.area(
                price_hist, x="Date", y="Close",
                labels={"Close": "Price (USD)", "Date": ""},
                color_discrete_sequence=["#6366f1"],
            )
            fig.update_traces(
                fill="tozeroy",
                fillcolor="rgba(99,102,241,0.08)",
                line=dict(width=1.8),
            )
            fig.update_layout(
                height=260,
                margin=dict(t=8, b=8, l=0, r=0),
                hovermode="x unified",
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            ui.plotly(fig).classes("w-full mb-4")
        else:
            ui.label("Price chart unavailable.").classes("text-gray-400 text-sm mb-4")

        ui.separator()

        # ── Two-column: fundamentals + thesis ─────────────────────────────────
        with ui.row().classes("gap-6 mt-4 items-start w-full"):

            # Left — fundamentals table
            with ui.card().classes("p-5 w-64 flex-none"):
                ui.label("Fundamentals").classes("font-semibold text-base mb-3")
                metrics = [
                    ("P/E Ratio",     fmt(row.get("pe_ratio"),     "x")),
                    ("P/B Ratio",     fmt(row.get("pb_ratio"),     "x")),
                    ("EV/EBITDA",     fmt(row.get("ev_ebitda"),    "x")),
                    ("FCF Yield",     fmt(row.get("fcf_yield"),    "%")),
                    ("ROE",           fmt(row.get("roe"),          "%")),
                    ("Debt/Equity",   fmt(row.get("debt_equity"),  "x")),
                    ("Value Score",   fmt(row.get("value_score"))),
                    ("Quality Score", fmt(row.get("quality_score"))),
                ]
                for label, value in metrics:
                    with ui.row().classes("justify-between py-1.5 border-b border-gray-100 last:border-0"):
                        ui.label(label).classes("text-sm text-gray-400")
                        ui.label(value).classes("text-sm font-semibold")

            # Right — thesis, risk, catalyst, SOE
            with ui.element("div").classes("flex-1 min-w-0"):
                ui.label("Agent Thesis").classes("font-semibold text-base mb-2")
                ui.html(
                    f"<div style='background:rgba(99,102,241,0.06);border-left:3px solid #6366f1;"
                    f"border-radius:0 8px 8px 0;padding:14px 18px;line-height:1.7;"
                    f"font-size:0.95em;margin-bottom:16px'>"
                    f"{row.get('thesis') or 'Thesis not yet generated.'}</div>"
                )

                with ui.row().classes("gap-4 w-full"):
                    with ui.element("div").classes("flex-1"):
                        ui.label("Key Risk").classes("font-semibold text-sm mb-1")
                        ui.html(
                            f"<div style='background:rgba(239,68,68,0.06);border-left:3px solid #ef4444;"
                            f"border-radius:0 8px 8px 0;padding:12px 16px;font-size:0.9em;line-height:1.55'>"
                            f"{row.get('key_risk') or '—'}</div>"
                        )
                    with ui.element("div").classes("flex-1"):
                        ui.label("Catalyst").classes("font-semibold text-sm mb-1")
                        ui.html(
                            f"<div style='background:rgba(34,197,94,0.06);border-left:3px solid #22c55e;"
                            f"border-radius:0 8px 8px 0;padding:12px 16px;font-size:0.9em;line-height:1.55'>"
                            f"{row.get('catalyst') or '—'}</div>"
                        )

                # Second-order effects
                soe_raw = row.get("second_order_effects")
                if soe_raw:
                    try:
                        effects = json.loads(soe_raw) if isinstance(soe_raw, str) else soe_raw
                        if effects:
                            ui.label("Second-Order Effects").classes("font-semibold text-sm mt-4 mb-2")
                            for effect in effects:
                                with ui.row().classes("items-start gap-2 mb-1"):
                                    ui.html("<span style='color:#94a3b8;margin-top:2px'>•</span>")
                                    ui.label(effect).classes("text-sm text-gray-600")
                    except (json.JSONDecodeError, TypeError):
                        pass

        # ── What changed this week ─────────────────────────────────────────────
        if latest_corr:
            ui.separator().classes("my-5")
            ui.label("What Changed This Week").classes("font-semibold text-base mb-3")
            ui.html(
                f"<div style='background:#f8fafc;border-radius:8px;padding:14px 18px;"
                f"font-size:0.92em;margin-bottom:10px;line-height:1.6'>"
                f"<strong>What happened:</strong>&nbsp;"
                f"{latest_corr.get('what_happened') or '—'}</div>"
                f"<div style='background:#f8fafc;border-radius:8px;padding:14px 18px;"
                f"font-size:0.92em;line-height:1.6'>"
                f"<strong>Agent's explanation:</strong>&nbsp;"
                f"{latest_corr.get('agents_explanation') or '—'}</div>"
            )

        # ── Conviction sparkline ───────────────────────────────────────────────
        history = get_ticker_history(ticker)
        if len(history) > 1:
            hist_df = pd.DataFrame(history)
            ui.separator().classes("my-5")
            ui.label("Conviction Over Time").classes("font-semibold text-base mb-2")
            fig_conv = px.line(
                hist_df, x="run_date", y="conviction",
                markers=True,
                color_discrete_sequence=["#6366f1"],
                labels={"run_date": "Week", "conviction": "Conviction"},
            )
            fig_conv.update_layout(
                height=180,
                margin=dict(t=8, b=8, l=0, r=0),
                yaxis_range=[0, 10],
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            ui.plotly(fig_conv).classes("w-full")

    page_wrap(body)


# ── Page 3: Correction Log ─────────────────────────────────────────────────────

@ui.page("/corrections")
def corrections_page():
    def body():
        ui.label("Self-Correction Log").classes("text-2xl font-bold mb-1")
        ui.label(
            "Generated each week when new data arrives. Builds up after the second weekly run."
        ).classes("text-sm text-gray-400 mb-4")

        corrections = get_all_corrections() or []
        if not corrections:
            ui.label("No corrections yet — run the agent for at least 2 consecutive weeks.").classes(
                "text-gray-400 mt-4"
            )
            return

        columns = [
            {"headerName": "Week",          "field": "run_date",         "width": 100},
            {"headerName": "Ticker",        "field": "ticker",           "width": 90,
             "cellStyle": {"fontWeight": "bold", "color": "#4f46e5"}},
            {"headerName": "Drift",         "field": "drift_signal",     "width": 120},
            {"headerName": "Error Type",    "field": "error_type",       "width": 150},
            {"headerName": "What Happened", "field": "what_happened",    "flex": 1,
             "wrapText": True, "autoHeight": True},
            {"headerName": "Explanation",   "field": "agents_explanation","flex": 2,
             "wrapText": True, "autoHeight": True},
        ]

        ui.aggrid({
            "columnDefs":    columns,
            "rowData":       corrections,
            "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
            "domLayout":     "autoHeight",
        }).classes("w-full")

    page_wrap(body)


# ── Page 4: Accuracy Tracker ────────────────────────────────────────────────────

@ui.page("/accuracy")
def accuracy_page():
    def body():
        ui.label("Accuracy Tracker").classes("text-2xl font-bold mb-1")
        ui.label(
            "Evaluates whether high-conviction calls were directionally correct after 4 weeks. "
            "Builds up over time."
        ).classes("text-sm text-gray-400 mb-6")

        corrections = get_all_corrections() or []
        if not corrections:
            ui.label("No correction data yet.").classes("text-gray-400")
            return

        df = pd.DataFrame(corrections)

        # Drift distribution bar chart
        drift_counts = df["drift_signal"].value_counts().reset_index()
        drift_counts.columns = ["drift_signal", "count"]
        if not drift_counts.empty:
            fig_drift = px.bar(
                drift_counts, x="drift_signal", y="count",
                color="drift_signal",
                color_discrete_map={
                    "Stable":       "#22c55e",
                    "Updated":      "#f59e0b",
                    "Contradicted": "#ef4444",
                },
                labels={"drift_signal": "Drift Signal", "count": "Count"},
                title="Thesis Drift Distribution",
            )
            fig_drift.update_layout(
                showlegend=False, height=280,
                margin=dict(t=40, b=8, l=0, r=0),
                plot_bgcolor="white", paper_bgcolor="white",
            )
            ui.plotly(fig_drift).classes("w-full max-w-lg mb-6")

        # Error type pie (only for Contradicted)
        contradicted = df[df["drift_signal"] == "Contradicted"]
        if not contradicted.empty:
            ui.label("Error Types (when thesis was Contradicted)").classes(
                "font-semibold text-base mb-2"
            )
            err_counts = contradicted["error_type"].value_counts().reset_index()
            err_counts.columns = ["error_type", "count"]
            fig_err = px.pie(
                err_counts, names="error_type", values="count",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_err.update_layout(height=260, margin=dict(t=8, b=8, l=0, r=0))
            ui.plotly(fig_err).classes("w-full max-w-sm")

    page_wrap(body)


# ── Run ────────────────────────────────────────────────────────────────────────

ui.run(
    port=8080,
    title="Investment Analyzer",
    favicon="📈",
    reload=False,
)
