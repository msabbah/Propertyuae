"""
build_html.py
Run once to generate a self-contained dashboard.html.
Usage: python3 build_html.py
"""

import os, sys
os.environ["STREAMLIT_CACHE_DISABLED"] = "1"  # suppress Streamlit warnings

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from datetime import date
from pathlib import Path

# ── silence Streamlit cache outside runtime ──────────────────────────────────
import streamlit as st
# Patch cache decorator to be a no-op when running outside Streamlit
import functools
def _noop_cache(**kwargs):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs_inner):
            return fn(*args, **kwargs_inner)
        return wrapper
    return decorator
st.cache_data = _noop_cache

# ── import project modules (after patching) ──────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
import importlib
import data_loader, data_processor, analytics, charts, config

# Reload to pick up the patched st.cache_data
for mod in [data_loader, data_processor, analytics, charts]:
    importlib.reload(mod)

from data_loader import load_data
from data_processor import (
    filter_data, get_monthly_median_rate, get_quarterly_volume,
    get_district_heatmap_data, get_layout_price_distribution,
    get_price_band_distribution, get_yoy_comparison,
    get_sale_type_monthly, get_market_share_by_district, compute_kpis,
)
from analytics import compute_entry_signals, project_trend, compute_momentum
from charts import (
    fig_price_trend_line, fig_yoy_overlay, fig_price_heatmap, fig_layout_box,
    fig_volume_bar, fig_off_plan_vs_ready, fig_market_share_pie,
    fig_price_band_histogram, fig_seasonality_wheel, fig_entry_signal_bars,
    fig_seasonal_component, fig_decomposition_panel, fig_trend_projection,
    fig_momentum_gauge,
)


def chart_div(fig, div_id=None) -> str:
    """Convert a Plotly figure to an HTML div string."""
    kwargs = dict(full_html=False, include_plotlyjs=False, config={"responsive": True})
    if div_id:
        kwargs["div_id"] = div_id
    return fig.to_html(**kwargs)


def kpi_card(label: str, value: str, delta: str = None, delta_positive: bool = None) -> str:
    delta_html = ""
    if delta:
        color = "#2ecc71" if delta_positive else "#e74c3c" if delta_positive is False else "#888"
        arrow = "▲" if delta_positive else "▼" if delta_positive is False else ""
        delta_html = f'<div class="kpi-delta" style="color:{color}">{arrow} {delta}</div>'
    return f"""
<div class="kpi-card">
  <div class="kpi-label">{label}</div>
  <div class="kpi-value">{value}</div>
  {delta_html}
</div>"""


def fmt_aed(val: float) -> str:
    if val is None: return "N/A"
    if val >= 1e9: return f"AED {val/1e9:.1f}B"
    if val >= 1e6: return f"AED {val/1e6:.0f}M"
    return f"AED {val:,.0f}"


# ── Load & filter data ────────────────────────────────────────────────────────
print("Loading data...")
df_raw = load_data()
df = filter_data(
    df_raw,
    property_types=config.FOCUS_PROPERTY_TYPES,
    sale_types=["off-plan", "ready"],
    min_transactions=1,  # no filtering at build time; charts handle it
)
print(f"  {len(df):,} records after filtering")


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: Price History
# ════════════════════════════════════════════════════════════════════════════
print("Building Tab 1: Price History...")
kpis = compute_kpis(df)
monthly = get_monthly_median_rate(df, min_transactions=10)
yoy_df = get_yoy_comparison(df, min_transactions=10)
heatmap_df = get_district_heatmap_data(df)
layout_df = get_layout_price_distribution(df, min_transactions=20)

t1_trend = chart_div(fig_price_trend_line(monthly), "t1_trend")
t1_yoy = chart_div(fig_yoy_overlay(yoy_df), "t1_yoy")
t1_heatmap = chart_div(fig_price_heatmap(heatmap_df), "t1_heatmap")
t1_layout = chart_div(fig_layout_box(layout_df), "t1_layout") if len(layout_df) > 0 else ""

rate = kpis["current_rate"]
yoy = kpis["yoy_change_pct"]
mom = kpis["momentum_pct"]

tab1_html = f"""
<div class="kpi-row">
  {kpi_card("Current Median Rate (last 3M)",
            f"AED {rate:,.0f}/SQM" if rate else "N/A")}
  {kpi_card("Year-on-Year Change",
            f"{yoy:+.1f}%" if yoy is not None else "N/A",
            f"{yoy:+.1f}%" if yoy is not None else None,
            yoy > 0 if yoy is not None else None)}
  {kpi_card("3-Month Momentum",
            f"{mom:+.1f}%" if mom is not None else "N/A",
            f"{mom:+.1f}%" if mom is not None else None,
            mom > 0 if mom is not None else None)}
</div>
<div class="chart-full">{t1_trend}</div>
<div class="chart-full">{t1_yoy}</div>
<div class="chart-full">{t1_heatmap}</div>
<details class="collapsible">
  <summary>Price Distribution by Bedroom Layout</summary>
  <div class="chart-full">{t1_layout}</div>
</details>
"""


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: Market Activity
# ════════════════════════════════════════════════════════════════════════════
print("Building Tab 2: Market Activity...")
vol_df = get_quarterly_volume(df, group_by=config.COL_PROPERTY_TYPE)
sale_type_df = get_sale_type_monthly(df)
share_df = get_market_share_by_district(df)
bands_df = get_price_band_distribution(df)

t2_vol = chart_div(fig_volume_bar(vol_df, group_by=config.COL_PROPERTY_TYPE), "t2_vol")
t2_split = chart_div(fig_off_plan_vs_ready(sale_type_df), "t2_split")
t2_pie = chart_div(fig_market_share_pie(share_df), "t2_pie")
t2_bands = chart_div(fig_price_band_histogram(bands_df), "t2_bands") if len(bands_df) > 0 else ""

tab2_html = f"""
<div class="kpi-row">
  {kpi_card("Total Transactions", f"{kpis['total_transactions']:,}")}
  {kpi_card("Total Transaction Value", fmt_aed(kpis['total_value_aed']))}
  {kpi_card("Off-Plan Share", f"{kpis['off_plan_share_pct']:.1f}%")}
</div>
<div class="chart-full">{t2_vol}</div>
<div class="chart-full">{t2_split}</div>
<div class="chart-row">
  <div class="chart-half">{t2_pie}</div>
  <div class="chart-half">{t2_bands}</div>
</div>
"""


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: Best Time to Enter
# ════════════════════════════════════════════════════════════════════════════
print("Building Tab 3: Best Time to Enter...")

ENTRY_COMBOS = [
    ("al reem island", "apartment", "Al Reem Island — Apartments"),
    ("yas island", "apartment", "Yas Island — Apartments"),
    ("al saadiyat island", "apartment", "Al Saadiyat Island — Apartments"),
]

entry_subtabs_nav = []
entry_subtabs_content = []

for i, (district, ptype, label) in enumerate(ENTRY_COMBOS):
    df_e = df[
        (df[config.COL_DISTRICT] == district) &
        (df[config.COL_PROPERTY_TYPE] == ptype)
    ]
    result = compute_entry_signals(df_e)

    tab_id = f"entry_{i}"
    entry_subtabs_nav.append(
        f'<button class="subtab-btn{"  subtab-active" if i == 0 else ""}" '
        f'onclick="showSubtab(\'{tab_id}\')">{label}</button>'
    )

    if not result["success"]:
        content = f'<p class="warn">Cannot compute signals: {result["reason"]}</p>'
    else:
        signals = result["signals"]
        wheel_div = chart_div(fig_seasonality_wheel(signals), f"wheel_{i}")
        bars_div = chart_div(fig_entry_signal_bars(signals), f"bars_{i}")
        comp_div = chart_div(fig_seasonal_component(signals), f"comp_{i}")

        best = ", ".join(f'<span class="badge-green">{m}</span>' for m in result["best_months"])
        worst = ", ".join(f'<span class="badge-red">{m}</span>' for m in result["worst_months"])

        content = f"""
<p class="data-note">
  {result['n_transactions']:,} transactions · {result['year_span']} · {result['amplitude_note']}
</p>
<div class="chart-row">
  <div class="chart-half">{wheel_div}</div>
  <div class="chart-half">{bars_div}</div>
</div>
<div class="chart-full">{comp_div}</div>
<div class="summary-card">
  <div class="summary-col">
    <strong>Best Entry Months:</strong><br>{best}
  </div>
  <div class="summary-col">
    <strong>Worst Entry Months:</strong><br>{worst}
  </div>
</div>
"""

    display = "block" if i == 0 else "none"
    entry_subtabs_content.append(
        f'<div id="{tab_id}" class="subtab-panel" style="display:{display}">{content}</div>'
    )

tab3_html = f"""
<div class="disclaimer">
  <strong>Disclaimer:</strong> This analysis identifies historical seasonal patterns.
  Past patterns do not guarantee future price movements. This is a statistical signal — not financial advice.
</div>
<div class="subtab-nav">{"".join(entry_subtabs_nav)}</div>
{"".join(entry_subtabs_content)}
"""


# ════════════════════════════════════════════════════════════════════════════
# TAB 4: Trend & Forecast
# ════════════════════════════════════════════════════════════════════════════
print("Building Tab 4: Trend & Forecast...")
series = monthly.set_index(config.COL_YEARMONTH)["median_rate"]
result_decomp = compute_entry_signals(df)

tab4_html = '<div class="disclaimer"><strong>Disclaimer:</strong> Projections use linear extrapolation of the trend component. Do not interpret beyond 6 months as reliable forecasts.</div>'

if result_decomp["success"]:
    decomp = result_decomp["decomposition"]

    # Momentum
    momentum_df = compute_momentum(series)
    if len(momentum_df) > 0:
        latest_mom = float(momentum_df["mom_3m"].iloc[-1])
        t4_gauge = chart_div(fig_momentum_gauge(latest_mom), "t4_gauge")
        tab4_html += f'<div class="chart-center">{t4_gauge}</div>'

    # Decomposition
    t4_decomp = chart_div(fig_decomposition_panel(decomp), "t4_decomp")
    tab4_html += f'<div class="chart-full">{t4_decomp}</div>'

    # Projection
    proj = project_trend(decomp.trend)
    if proj["success"]:
        if proj["high_uncertainty"]:
            tab4_html += '<p class="warn">⚠ High uncertainty: residual variance is increasing. Treat projection with extra caution.</p>'

        slope = proj["slope_per_month"]
        direction = "Upward" if slope > 0 else "Downward"
        r2 = proj["r_squared"]

        tab4_html += f"""
<div class="kpi-row" style="justify-content:flex-start;gap:16px;margin-bottom:16px">
  {kpi_card("Trend Direction", direction, f"AED {slope:+,.0f}/SQM per month", slope > 0)}
  {kpi_card("Trend R²", f"{r2:.3f}")}
</div>
"""
        t4_proj = chart_div(fig_trend_projection(proj["historical"], proj["projection"]), "t4_proj")
        tab4_html += f'<div class="chart-full">{t4_proj}</div>'

    # Data table
    tbl_df = monthly.tail(12).copy()
    tbl_df[config.COL_YEARMONTH] = tbl_df[config.COL_YEARMONTH].dt.strftime("%b %Y")
    tbl_df["median_rate"] = tbl_df["median_rate"].round(0).astype(int)

    rows_html = "".join(
        f"<tr><td>{r[config.COL_YEARMONTH]}</td>"
        f"<td>AED {r['median_rate']:,}/SQM</td>"
        f"<td>{r['transaction_count']:,}</td></tr>"
        for _, r in tbl_df.sort_values(config.COL_YEARMONTH, ascending=False).iterrows()
    )
    tab4_html += f"""
<details class="collapsible">
  <summary>Monthly Data Table (last 12 months)</summary>
  <table class="data-table">
    <thead><tr><th>Month</th><th>Median Rate</th><th>Transactions</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</details>
"""
else:
    tab4_html += f'<p class="warn">Decomposition failed: {result_decomp["reason"]}</p>'


# ════════════════════════════════════════════════════════════════════════════
# Assemble HTML
# ════════════════════════════════════════════════════════════════════════════
print("Assembling HTML...")

generated_date = date.today().strftime("%B %d, %Y")

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Abu Dhabi Real Estate Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f1117;
    color: #e0e0e0;
    min-height: 100vh;
  }}
  /* ── Header ── */
  .header {{
    background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
    border-bottom: 1px solid #2d3748;
    padding: 24px 40px 20px;
  }}
  .header h1 {{
    font-size: 1.8rem;
    font-weight: 700;
    color: #f0f4ff;
    letter-spacing: -0.5px;
  }}
  .header p {{
    font-size: 0.85rem;
    color: #8892a4;
    margin-top: 4px;
  }}
  /* ── Main Tab Nav ── */
  .tab-nav {{
    display: flex;
    gap: 4px;
    background: #13161f;
    padding: 12px 40px 0;
    border-bottom: 1px solid #2d3748;
  }}
  .tab-btn {{
    padding: 10px 20px;
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    color: #8892a4;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    border-radius: 4px 4px 0 0;
  }}
  .tab-btn:hover {{ color: #c8d0e0; background: #1a1f2e; }}
  .tab-btn.active {{
    color: #4e8cff;
    border-bottom-color: #4e8cff;
    background: #1a1f2e;
  }}
  /* ── Tab Panels ── */
  .tab-panel {{ display: none; padding: 28px 40px 40px; }}
  .tab-panel.active {{ display: block; }}
  /* ── KPI Cards ── */
  .kpi-row {{
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }}
  .kpi-card {{
    background: #1a1f2e;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 16px 24px;
    min-width: 200px;
    flex: 1;
  }}
  .kpi-label {{
    font-size: 0.75rem;
    color: #8892a4;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }}
  .kpi-value {{
    font-size: 1.6rem;
    font-weight: 700;
    color: #f0f4ff;
    letter-spacing: -0.5px;
  }}
  .kpi-delta {{
    font-size: 0.85rem;
    font-weight: 500;
    margin-top: 4px;
  }}
  /* ── Charts ── */
  .chart-full {{ margin-bottom: 24px; }}
  .chart-row {{
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }}
  .chart-half {{ flex: 1; min-width: 300px; }}
  .chart-center {{
    display: flex;
    justify-content: center;
    margin-bottom: 24px;
  }}
  .chart-center > div {{ max-width: 480px; width: 100%; }}
  /* ── Sub-tabs (Tab 3) ── */
  .subtab-nav {{
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }}
  .subtab-btn {{
    padding: 8px 16px;
    background: #1a1f2e;
    border: 1px solid #2d3748;
    border-radius: 20px;
    color: #8892a4;
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .subtab-btn:hover {{ border-color: #4e8cff; color: #c8d0e0; }}
  .subtab-btn.subtab-active {{ background: #4e8cff22; border-color: #4e8cff; color: #4e8cff; }}
  /* ── Misc ── */
  .disclaimer {{
    background: #1a2033;
    border-left: 3px solid #4e8cff;
    border-radius: 0 6px 6px 0;
    padding: 12px 16px;
    font-size: 0.82rem;
    color: #a0aec0;
    margin-bottom: 20px;
    line-height: 1.5;
  }}
  .warn {{
    background: #2a1a00;
    border-left: 3px solid #f39c12;
    border-radius: 0 6px 6px 0;
    padding: 10px 14px;
    font-size: 0.82rem;
    color: #f0c070;
    margin-bottom: 16px;
  }}
  .data-note {{
    font-size: 0.8rem;
    color: #8892a4;
    margin-bottom: 16px;
  }}
  .summary-card {{
    display: flex;
    gap: 32px;
    background: #1a1f2e;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 20px 24px;
    margin-top: 16px;
    flex-wrap: wrap;
  }}
  .summary-col {{ flex: 1; min-width: 180px; line-height: 2; }}
  .badge-green {{
    display: inline-block;
    background: #1a3a2a;
    color: #2ecc71;
    border: 1px solid #2ecc71;
    border-radius: 12px;
    padding: 1px 10px;
    font-size: 0.8rem;
    margin: 2px;
  }}
  .badge-red {{
    display: inline-block;
    background: #3a1a1a;
    color: #e74c3c;
    border: 1px solid #e74c3c;
    border-radius: 12px;
    padding: 1px 10px;
    font-size: 0.8rem;
    margin: 2px;
  }}
  .collapsible {{
    background: #1a1f2e;
    border: 1px solid #2d3748;
    border-radius: 8px;
    margin-bottom: 24px;
    overflow: hidden;
  }}
  .collapsible summary {{
    padding: 14px 20px;
    font-size: 0.9rem;
    color: #a0b0c8;
    cursor: pointer;
    user-select: none;
    list-style: none;
  }}
  .collapsible summary::before {{
    content: "▶  ";
    font-size: 0.7rem;
    opacity: 0.7;
  }}
  .collapsible[open] summary::before {{ content: "▼  "; }}
  .collapsible summary:hover {{ color: #c8d8f0; }}
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    margin: 0 16px 16px;
    width: calc(100% - 32px);
  }}
  .data-table th {{
    background: #13161f;
    color: #8892a4;
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.5px;
    padding: 10px 16px;
    text-align: left;
    border-bottom: 1px solid #2d3748;
  }}
  .data-table td {{
    padding: 9px 16px;
    border-bottom: 1px solid #1e2433;
    color: #c8d0e0;
  }}
  .data-table tr:hover td {{ background: #1e2433; }}
</style>
</head>
<body>

<div class="header">
  <h1>🏙 Abu Dhabi Residential Property Market</h1>
  <p>Transaction data 2019–2026 &nbsp;·&nbsp; {len(df):,} transactions &nbsp;·&nbsp; Generated {generated_date} &nbsp;·&nbsp; Source: Abu Dhabi DMT</p>
</div>

<nav class="tab-nav">
  <button class="tab-btn active" onclick="showTab('t1')">📈 Price History</button>
  <button class="tab-btn" onclick="showTab('t2')">📊 Market Activity</button>
  <button class="tab-btn" onclick="showTab('t3')">🎯 Best Time to Enter</button>
  <button class="tab-btn" onclick="showTab('t4')">🔮 Trend &amp; Forecast</button>
</nav>

<div id="t1" class="tab-panel active">{tab1_html}</div>
<div id="t2" class="tab-panel">{tab2_html}</div>
<div id="t3" class="tab-panel">{tab3_html}</div>
<div id="t4" class="tab-panel">{tab4_html}</div>

<script>
function showTab(id) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.currentTarget.classList.add('active');
  // Trigger Plotly resize so charts fill their containers
  window.dispatchEvent(new Event('resize'));
}}

function showSubtab(id) {{
  document.querySelectorAll('.subtab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('subtab-active'));
  document.getElementById(id).style.display = 'block';
  event.currentTarget.classList.add('subtab-active');
  window.dispatchEvent(new Event('resize'));
}}
</script>
</body>
</html>
"""

out_path = Path(__file__).parent / "dashboard.html"
out_path.write_text(html, encoding="utf-8")
size_kb = out_path.stat().st_size / 1024
print(f"\n✓ dashboard.html generated ({size_kb:.0f} KB)")
print(f"  Open: file://{out_path.resolve()}")
