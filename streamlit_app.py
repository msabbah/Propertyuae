import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime as _dt
from streamlit_option_menu import option_menu
import config
from data_loader import (
    load_data, get_filter_options, clean_raw_df, merge_transactions,
    save_merged, load_merged_if_exists, delete_merged,
)
from data_processor import (
    filter_data, get_monthly_median_rate, get_quarterly_volume,
    get_district_heatmap_data, get_layout_price_distribution,
    get_price_band_distribution, get_yoy_comparison,
    get_sale_type_monthly, get_market_share_by_district, compute_kpis,
    get_project_screener, get_project_monthly_rate,
    get_project_district_monthly, get_project_quarterly_volume,
)
from analytics import compute_entry_signals, project_trend, compute_momentum, decompose_time_series
from charts import (
    fig_price_trend_line, fig_yoy_overlay, fig_price_heatmap, fig_layout_box, fig_price_distribution,
    fig_volume_bar, fig_off_plan_vs_ready, fig_market_share_pie, fig_price_band_histogram,
    fig_seasonality_wheel, fig_entry_signal_bars, fig_seasonal_component,
    fig_decomposition_panel, fig_trend_projection, fig_momentum_gauge,
    fig_momentum_gauge_dual,
    fig_project_screener_scatter, fig_project_price_trend,
    fig_project_volume_bar, fig_pf_project_asking_trend,
    fig_asking_trend_line, fig_asking_vs_actual_trend,
    fig_asking_pct_change_bar, fig_asking_cumulative_line,
)


# ── Market state helpers ────────────────────────────────────────────────────
MARKET_STATE_COPY = {
    "strong_growth": {
        "label": "Strong Growth",
        "subtitle": "Prices and momentum both rising",
        "action": "Consider acting soon — market is appreciating",
        "color": "#27ae60",
        "bg": "#eafaf1",
    },
    "moderate_growth": {
        "label": "Moderate Growth",
        "subtitle": "Steady appreciation, low volatility",
        "action": "Favourable conditions for entry",
        "color": "#2ecc71",
        "bg": "#f0faf4",
    },
    "stable": {
        "label": "Stable Market",
        "subtitle": "Prices flat, momentum neutral",
        "action": "Entry depends on district and timing — check Best Time to Buy tab",
        "color": "#f39c12",
        "bg": "#fef9e7",
    },
    "declining": {
        "label": "Caution",
        "subtitle": "Prices falling or momentum negative",
        "action": "Wait for momentum to stabilise before entering",
        "color": "#e74c3c",
        "bg": "#fdedec",
    },
    "insufficient_data": {
        "label": "Insufficient Data",
        "subtitle": "Not enough data for this filter selection",
        "action": "Broaden your filters to get a signal",
        "color": "#95a5a6",
        "bg": "#f8f9fa",
    },
}


def classify_market_state(yoy, momentum):
    if yoy is None or momentum is None:
        return "insufficient_data"
    if yoy > config.MARKET_STATE_STRONG_YOY and momentum > config.MARKET_STATE_STRONG_MOM:
        return "strong_growth"
    elif yoy > 0 and momentum >= 0:
        return "moderate_growth"
    elif yoy < config.MARKET_STATE_DECLINE_YOY or (yoy < 0 and momentum < config.MARKET_STATE_DECLINE_MOM):
        return "declining"
    else:
        return "stable"


def build_filter_summary(sel_districts, sel_property_types, sel_sale_types, sel_years, sel_layouts, n_rows):
    parts = []
    if sel_districts:
        parts.append(sel_districts[0] if len(sel_districts) == 1 else f"{len(sel_districts)} districts")
    else:
        parts.append("All districts")

    if sel_property_types and len(sel_property_types) < len(config.FOCUS_PROPERTY_TYPES):
        type_labels = [config.PROPERTY_TYPE_LABELS.get(t, t.title()) for t in sel_property_types]
        parts.append(" & ".join(type_labels))

    if sel_sale_types:
        if len(sel_sale_types) == 1:
            parts.append(sel_sale_types[0].title())
        else:
            parts.append("Off-Plan + Ready")

    year_str = f"{sel_years[0]}–{sel_years[1]}" if sel_years[0] != sel_years[1] else str(sel_years[0])
    parts.append(year_str)

    if sel_layouts:
        layout_str = ", ".join(sel_layouts[:2])
        if len(sel_layouts) > 2:
            layout_str += f" +{len(sel_layouts) - 2}"
        parts.append(layout_str)

    parts.append(f"**{n_rows:,} transactions**")
    return " · ".join(parts)


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Abu Dhabi Real Estate Dashboard",
    page_icon="🏙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Sidebar: placeholder text white ─────────────────────────────────────── */
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] [data-baseweb="select"] [data-testid="stWidgetLabel"],
[data-testid="stSidebar"] [class*="placeholder"] {
    color: #ffffff !important;
    opacity: 1 !important;
}

/* ── Sidebar: dark navy ───────────────────────────────────────────────────── */
[data-testid="stSidebar"] > div:first-child {
    background-color: #0d1f35 !important;
}
[data-testid="stSidebar"] {
    background-color: #0d1f35 !important;
}

/* All text white/light */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span:not([data-baseweb="tag"] span),
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div.stMarkdown p,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small,
[data-testid="stSidebar"] .stNumberInput input {
    color: #d0dcea !important;
}

/* Headers */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
    font-size: 0.95rem !important;
    font-weight: 700 !important;
}

/* Section labels */
[data-testid="stSidebar"] .sidebar-section-label {
    font-size: 0.62rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.13em !important;
    text-transform: uppercase !important;
    color: #7aafd4 !important;
    margin-top: 14px;
    margin-bottom: 2px;
}

/* Input / select backgrounds */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background-color: #122840 !important;
    border-color: #1e4068 !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #d0dcea !important;
}
[data-testid="stSidebar"] input[type="number"] {
    background-color: #122840 !important;
    border-color: #1e4068 !important;
    color: #d0dcea !important;
}

/* Multiselect tags */
[data-testid="stSidebar"] [data-baseweb="tag"] {
    background-color: #1e4068 !important;
}
[data-testid="stSidebar"] [data-baseweb="tag"] span {
    color: #cce0f5 !important;
}

/* Slider thumb */
[data-testid="stSidebar"] [role="slider"] {
    background-color: #4a9edd !important;
    border-color: #4a9edd !important;
}

/* Divider */
[data-testid="stSidebar"] hr {
    border-color: #1e3a5f !important;
}

/* Button */
[data-testid="stSidebar"] .stButton > button {
    background-color: transparent !important;
    border: 1px solid #2a4f72 !important;
    color: #7aafd4 !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #1a3353 !important;
    border-color: #4a9edd !important;
    color: #cce0f5 !important;
}

/* Expander */
[data-testid="stSidebar"] details summary {
    color: #7aafd4 !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
}

/* ── Main content ─────────────────────────────────────────────────────────── */
h1 {
    font-size: 1.45rem !important;
    font-weight: 700 !important;
    color: #0d1f35 !important;
    letter-spacing: -0.01em;
}
</style>
""", unsafe_allow_html=True)

st.title("Abu Dhabi Residential Property Market")
st.caption("Transaction data 2019–2026 · Source: Abu Dhabi Department of Municipalities and Transport")


# ── Load data ─────────────────────────────────────────────────────────────────
# Priority: session state (set this run) → persisted merged file → original CSV
_base_df = load_data()

if "df_raw_active" not in st.session_state:
    _persisted = load_merged_if_exists()
    if _persisted is not None:
        st.session_state["df_raw_active"] = _persisted

df_raw = st.session_state.get("df_raw_active", _base_df)
options = get_filter_options(df_raw)

_latest_date = df_raw[config.COL_DATE].max()
_upload_note = " · *updated from upload*" if "df_raw_active" in st.session_state else ""
_current_period = pd.Period(pd.Timestamp.now(), freq="M")
_latest_period = pd.Period(_latest_date, freq="M")
_partial_note = (
    f" · ⚠️ *{_latest_date.strftime('%b %Y')} data is partial ({_latest_date.day} days)*"
    if _latest_period == _current_period else ""
)
st.caption(
    f"Latest transaction: **{_latest_date.strftime('%b %d, %Y')}** · "
    f"{len(df_raw):,} residential transactions loaded{_upload_note}{_partial_note}"
)


# ── Onboarding guide ────────────────────────────────────────────────────────
with st.expander("How to use this dashboard", expanded=False):
    st.markdown(
        """
**Start here:** Use the sidebar on the left to narrow your view by district, property type, sale type, and year range. All tabs update instantly.

| Tab | What it answers |
|-----|----------------|
| **Price History** | What are prices doing? Which districts appreciate fastest? |
| **Market Activity** | Is transaction volume growing? Where is liquidity concentrated? |
| **Entry Timing** | Which months historically offer the best entry price and lowest competition? |
| **Trend & Outlook** | What does the decomposed trend and 6-month projection look like? |
| **Asking vs Actual** | How do Property Finder asking prices compare to actual transaction prices? |

**Tips:**
- Select a **single district** for a focused investment signal
- Use **Min. Transactions per Data Point** in the sidebar to control noise — higher values = cleaner signal
- The **Entry Timing** tab has its own district/type selector for deep-dive seasonal analysis
- The **verdict card** (top right) gives a quick market state read for your current selection
- Use **Update Transaction Data** in the sidebar to load a newer CSV — all tabs refresh automatically
        """
    )


# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='padding:8px 4px 6px 4px;'>"
        "<div style='font-size:0.65rem;font-weight:700;letter-spacing:0.14em;"
        "text-transform:uppercase;color:#4a9edd;margin-bottom:2px;'>Abu Dhabi</div>"
        "<div style='font-size:1.05rem;font-weight:800;color:#ffffff;line-height:1.2;'>"
        "Property Intelligence</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── SEGMENT ───────────────────────────────────────────────────────────────
    st.markdown("<div class='sidebar-section-label'>Segment</div>", unsafe_allow_html=True)
    sel_property_types = st.multiselect(
        "Property Type",
        options=config.FOCUS_PROPERTY_TYPES,
        default=config.FOCUS_PROPERTY_TYPES,
        format_func=lambda x: config.PROPERTY_TYPE_LABELS.get(x, x.title()),
        help="Apartments are the most liquid segment. Villas and townhouses have lower volumes but higher values per transaction.",
        label_visibility="collapsed",
    )

    sel_sale_types = st.multiselect(
        "Sale Type",
        options=["off-plan", "ready"],
        default=["off-plan", "ready"],
        format_func=lambda x: x.title(),
        help="Off-Plan: units sold before or during construction. Ready: completed units. A high off-plan share signals developer-driven demand.",
        label_visibility="collapsed",
        placeholder="All sale types",
    )

    layout_options = [l for l in options["layouts"] if l and l != "unclassified"]
    sel_layouts = st.multiselect(
        "Bedroom Layout",
        options=layout_options,
        default=[],
        placeholder="All bedroom layouts",
        help="Filter by unit size. Leave blank to include all bedroom configurations.",
        label_visibility="collapsed",
    )

    # ── GEOGRAPHY ─────────────────────────────────────────────────────────────
    st.markdown("<div class='sidebar-section-label'>Geography</div>", unsafe_allow_html=True)
    # Precompute transaction counts per district for live feedback
    _district_counts = (
        df_raw.groupby(df_raw[config.COL_DISTRICT].str.title())
        .size()
        .to_dict()
    )
    default_districts = [d for d in config.TOP_DISTRICTS[:5]
                         if d.lower() in [opt.lower() for opt in options["districts"]]]
    sel_districts = st.multiselect(
        "District",
        options=options["districts"],
        default=default_districts,
        format_func=lambda d: f"{d}  ({_district_counts.get(d, 0):,})",
        help="Number in brackets = total transactions in dataset. Select one district for a focused signal, or multiple for a market-wide view.",
        label_visibility="collapsed",
        placeholder="All districts",
    )

    # ── TIME PERIOD ───────────────────────────────────────────────────────────
    st.markdown("<div class='sidebar-section-label'>Time Period</div>", unsafe_allow_html=True)
    min_year = int(min(options["years"]))
    max_year = int(max(options["years"]))
    sel_years = st.slider(
        "Year Range",
        min_year, max_year, (min_year, max_year),
        help="Narrow the date range to focus on a recent cycle or a specific period.",
    )

    # ── SIGNAL QUALITY ────────────────────────────────────────────────────────
    st.markdown("<div class='sidebar-section-label'>Signal Quality</div>", unsafe_allow_html=True)
    min_tx = st.number_input(
        "Min. transactions per data point",
        min_value=1, max_value=500, value=10, step=5,
        help="Hides data points backed by fewer transactions than this threshold. Raise to 20–30 to reduce noise in thin markets.",
    )

    st.divider()
    st.caption("Tabs 1 · 2 · 4 · 5 use these filters. Tab 3 has its own selectors.")

    # ── DATA CONTROLS ─────────────────────────────────────────────────────────
    st.markdown("<div class='sidebar-section-label'>Data</div>", unsafe_allow_html=True)
    with st.expander("Update Transaction Data", expanded=False):
        st.caption(
            "Upload a newer transactions CSV to extend the dataset. "
            "New rows are merged in and duplicates are automatically removed. "
            "All tabs update instantly."
        )
        _sidebar_csv = st.file_uploader(
            "Transactions CSV",
            type=["csv"],
            key="sidebar_csv_uploader",
            label_visibility="collapsed",
        )
        if _sidebar_csv is not None:
            try:
                with st.spinner("Loading and deduplicating…"):
                    _uploaded_raw = pd.read_csv(_sidebar_csv, encoding="utf-8-sig")
                    _uploaded_clean = clean_raw_df(_uploaded_raw)
                    _merged = merge_transactions(_base_df, _uploaded_clean)
                    _new_count = len(_merged) - len(_base_df)
                    save_merged(_merged)
                    st.session_state["df_raw_active"] = _merged
                st.success(
                    f"+{_new_count:,} new rows merged "
                    f"({len(_merged):,} total). Saved — survives page refresh."
                )
                st.rerun()
            except Exception as _e:
                st.error(f"Upload failed: {_e}")

        if "df_raw_active" in st.session_state:
            if st.button("Revert to original CSV", use_container_width=True):
                delete_merged()
                del st.session_state["df_raw_active"]
                st.rerun()

    st.divider()
    if st.button("Reset all filters", use_container_width=True):
        _preserved = st.session_state.get("df_raw_active")
        st.session_state.clear()
        if _preserved is not None:
            st.session_state["df_raw_active"] = _preserved
        st.rerun()


# ── Apply global filters ────────────────────────────────────────────────────
df = filter_data(
    df_raw,
    districts=sel_districts if sel_districts else None,
    property_types=sel_property_types if sel_property_types else None,
    sale_types=sel_sale_types if sel_sale_types else None,
    layouts=sel_layouts if sel_layouts else None,
    year_range=sel_years,
)

if len(df) == 0:
    st.warning(
        "No transactions match the current filters. "
        "Try broadening the district selection, removing layout filters, or expanding the year range."
    )
    st.stop()

# ── Compute KPIs once ────────────────────────────────────────────────────────
kpis = compute_kpis(df)

rate = kpis["current_rate"]
yoy  = kpis["yoy_change_pct"]
mom  = kpis["momentum_pct"]

market_state = classify_market_state(yoy, mom)
ms = MARKET_STATE_COPY[market_state]

# ── Single consolidated status bar ──────────────────────────────────────────
filter_summary = build_filter_summary(
    sel_districts, sel_property_types, sel_sale_types, sel_years, sel_layouts, len(df)
)
st.markdown(
    f"<div style='font-size:0.78rem;color:#5a6a7a;padding:2px 0 8px 0;'>"
    f"{filter_summary}"
    f"</div>",
    unsafe_allow_html=True,
)

# ── Verdict card — full width, anchors the page ──────────────────────────────
st.markdown(
    f"""<div style="background:{ms['bg']};border-left:5px solid {ms['color']};
    padding:14px 20px;border-radius:6px;line-height:1.7;margin-bottom:12px;">
    <span style="font-weight:800;color:{ms['color']};font-size:16px;">{ms['label']}</span>
    <span style="font-size:13px;color:#555;margin-left:12px;">{ms['subtitle']}</span>
    <span style="font-size:12px;color:#777;margin-left:12px;">→ {ms['action']}</span>
    </div>""",
    unsafe_allow_html=True,
)

# ── Three KPI metrics below verdict ─────────────────────────────────────────
col_rate, col_yoy, col_mom = st.columns(3)

with col_rate:
    st.metric(
        "Median Price (last 3M)",
        f"AED {rate:,.0f}/sqm" if rate else "N/A",
        help="Median transaction price per square metre over the last 3 months of available data.",
    )
with col_yoy:
    st.metric(
        "Year-on-Year",
        f"{yoy:+.1f}%" if yoy is not None else "N/A",
        delta=f"{yoy:+.1f}%" if yoy is not None else None,
        help="Change in median price vs the same 3-month window one year ago.",
    )
with col_mom:
    st.metric(
        "3M Momentum",
        f"{mom:+.1f}%" if mom is not None else "N/A",
        delta=f"{mom:+.1f}%" if mom is not None else None,
        help="Change in median price vs the prior 3-month window. Positive = prices accelerating.",
    )

st.divider()


# ── Navigation ───────────────────────────────────────────────────────────────
_tab_names = [
    "Market Activity",
    "Price History",
    "Entry Timing",
    "Trend & Outlook",
    "Asking vs Actual",
    "Asking Price Analysis",
    "Project Intelligence",
]
_tab_icons = [
    "bar-chart-fill",
    "graph-up",
    "clock-history",
    "activity",
    "arrows-collapse",
    "search",
    "building",
]

selected_tab = option_menu(
    menu_title=None,
    options=_tab_names,
    icons=_tab_icons,
    orientation="horizontal",
    default_index=0,
    styles={
        "container": {
            "padding": "0 !important",
            "background-color": "#f4f6f9",
            "border-bottom": "2px solid #dde4ed",
            "margin-bottom": "16px",
        },
        "nav-link": {
            "font-size": "0.82rem",
            "font-weight": "600",
            "color": "#5a6a7a",
            "padding": "10px 18px",
            "border-radius": "0",
            "--hover-color": "#e8eef5",
        },
        "nav-link-selected": {
            "background-color": "#ffffff",
            "color": "#1e3a5f",
            "border-bottom": "2px solid #1e3a5f",
            "font-weight": "700",
        },
        "icon": {"font-size": "0.78rem"},
    },
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Price History
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Price History":
    color_by_opt = st.radio(
        "Break down trend line by:",
        ["None", "District", "Property Type"],
        horizontal=True,
        help="Split the trend line to compare segments side by side.",
    )
    color_by_col = {
        "None": None,
        "District": config.COL_DISTRICT,
        "Property Type": config.COL_PROPERTY_TYPE,
    }[color_by_opt]

    monthly = get_monthly_median_rate(df, group_by=color_by_col, min_transactions=min_tx)
    if len(monthly) == 0:
        st.info(
            "Not enough data to render a trend line for the current filters. "
            "Try reducing the Min. Transactions threshold or broadening your selection."
        )
    else:
        st.plotly_chart(fig_price_trend_line(monthly, color_by=color_by_col), use_container_width=True)
        st.caption(
            f"Monthly median price per sqm. Each point requires at least {min_tx} transactions. "
            "Use the breakdown toggle above to compare districts or property types."
        )

    st.subheader("Intra-Year Seasonality")
    _yoy_view = st.radio(
        "View",
        ["Absolute (AED/sqm)", "Seasonal Index (% vs annual avg)"],
        horizontal=True,
        help=(
            "**Absolute** shows actual AED/sqm — useful to see price levels.\n\n"
            "**Seasonal Index** normalises each year to its own annual median, "
            "revealing the seasonal *shape* independent of price level. "
            "Values above 0% = months that are typically more expensive than average."
        ),
    )
    _yoy_indexed = _yoy_view.startswith("Seasonal")

    yoy_df = get_yoy_comparison(df, min_transactions=min_tx)
    if len(yoy_df) > 0:
        st.plotly_chart(
            fig_yoy_overlay(yoy_df, indexed=_yoy_indexed),
            use_container_width=True,
        )
        if _yoy_indexed:
            st.caption(
                "Each line is one calendar year, normalised so 0% = that year's own annual median. "
                "Months consistently above 0% are seasonally expensive; below 0% are seasonally cheap. "
                "Overlapping lines across years indicate a stable seasonal pattern. "
                "Use sidebar filters to study a specific district, type, or layout."
            )
        else:
            st.caption(
                "Each line represents a calendar year. "
                "Diverging lines signal accelerating or decelerating price trends relative to prior years. "
                "Use sidebar filters to narrow to a district, type, or layout."
            )
    else:
        st.info("Not enough data for the current filters. Try broadening your sidebar selection.")

    heatmap_df = get_district_heatmap_data(df, min_transactions=min_tx)
    if len(heatmap_df) > 0:
        st.plotly_chart(fig_price_heatmap(heatmap_df), use_container_width=True)
        st.caption(
            "Year-on-year price change per district. Green = appreciation, red = depreciation. "
            "Blank cells = fewer than the minimum transaction threshold. "
            "Look for consistently green districts — they have sustained appreciation."
        )
    else:
        st.info(
            "Not enough district-level data to render the heatmap. "
            "Try lowering Min. Transactions or selecting more districts."
        )

    st.subheader("Price / sqm Distribution")
    _dist_group_opt = st.radio(
        "Group curves by",
        ["Bedroom Layout", "Property Type", "District"],
        horizontal=True,
        help="Split the distribution into one curve per segment.",
    )
    _dist_group_col = {
        "Bedroom Layout": config.COL_LAYOUT,
        "Property Type":  config.COL_PROPERTY_TYPE,
        "District":       config.COL_DISTRICT,
    }[_dist_group_opt]

    _dist_df = df.dropna(subset=[config.COL_RATE])
    if len(_dist_df) >= 30:
        st.plotly_chart(
            fig_price_distribution(_dist_df, group_by=_dist_group_col),
            use_container_width=True,
        )
        st.caption(
            "Kernel density estimate — shows the shape of the price distribution for each segment. "
            "Taller, narrower peaks = more uniform pricing. "
            "Wide or bimodal curves = mixed supply (e.g. off-plan + ready in same layout). "
            "Dashed vertical line = median. Responds to all sidebar filters."
        )
    else:
        st.info("Not enough data for a distribution curve. Broaden your sidebar filters.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Market Activity
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Market Activity":
    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric(
            "Total Transactions",
            f"{kpis['total_transactions']:,}",
            help="Number of qualifying residential transactions in the selected period and filters.",
        )
    with k2:
        val = kpis["total_value_aed"]
        if val >= 1e9:
            st.metric("Total Transaction Value", f"AED {val/1e9:.1f}B")
        else:
            st.metric("Total Transaction Value", f"AED {val/1e6:.0f}M")
    with k3:
        st.metric(
            "Off-Plan Share",
            f"{kpis['off_plan_share_pct']:.1f}%",
            help="Share of off-plan transactions. Above 60% = speculative demand. Below 40% = mostly end-users and investors buying completed stock.",
        )

    st.divider()

    vol_group_opt = st.radio(
        "Break down volume by:",
        ["None", "Property Type", "District"],
        horizontal=True,
        help="Stack bars by segment to see which property types or districts are driving market activity.",
    )
    vol_group_col = {
        "None": None,
        "Property Type": config.COL_PROPERTY_TYPE,
        "District": config.COL_DISTRICT,
    }[vol_group_opt]

    vol_df = get_quarterly_volume(df, group_by=vol_group_col)
    st.plotly_chart(fig_volume_bar(vol_df, group_by=vol_group_col), use_container_width=True)
    st.caption(
        "Quarterly transaction count. Volume growth alongside price growth = broad-based demand. "
        "Volume growth without price growth may signal oversupply."
    )

    sale_type_df = get_sale_type_monthly(df)
    if len(sale_type_df) > 0:
        st.plotly_chart(fig_off_plan_vs_ready(sale_type_df), use_container_width=True)
        st.caption(
            "Monthly split between off-plan and ready transactions. A rising off-plan share can signal "
            "developer activity and speculative demand — watch for divergence from the ready market."
        )

    col_a, col_b = st.columns(2)
    with col_a:
        share_df = get_market_share_by_district(df)
        st.plotly_chart(fig_market_share_pie(share_df), use_container_width=True)
        st.caption(
            "Transaction share by district. Concentrated share = high liquidity in those locations, "
            "which typically means easier resale and tighter bid-ask spreads."
        )
    with col_b:
        bands_df = get_price_band_distribution(df)
        if len(bands_df) > 0:
            st.plotly_chart(fig_price_band_histogram(bands_df), use_container_width=True)
            st.caption(
                "Transactions concentrated in the most active price bands have deeper resale markets. "
                "Buying in a thin band (few transactions) increases liquidity risk."
            )
        else:
            st.info("No price band data available for the current filters.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Best Time to Buy
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Entry Timing":
    st.info(
        "**How to read this tab:** The charts below identify months where prices have historically "
        "been below the annual average — green = better entry. This is based on seasonal decomposition "
        "of transaction data, not a prediction. Use it to time entry within a year, "
        "not to call market tops or bottoms."
    )

    if sel_sale_types and len(sel_sale_types) == 1:
        st.warning(
            f"⚠️ The sidebar **Sale Type** filter is set to **{sel_sale_types[0].title()} only**. "
            "Seasonal analysis below reflects that sale type exclusively, which may differ from "
            "the market-wide seasonal pattern. To see the full picture, select both Off-Plan and Ready in the sidebar."
        )

    with st.expander("Methodology & limitations"):
        st.markdown(
            """
**How the seasonal signal is computed:**

1. Monthly median price per sqm is calculated for the selected district and property type
2. Seasonal decomposition (`statsmodels`) extracts the repeating 12-month cycle
3. Each calendar month gets an average seasonal component → normalised to a 0–100 score
4. Volume is computed similarly and combined: **Composite = 60% price signal + 40% volume signal**
5. Months are ranked into 4 tiers: **Tier 1** (best entry) → **Tier 4** (avoid)

**Limitations:** Requires at least 3 full years of data (36 months) for a statistically reliable signal.
Between 24–36 months, signals are shown but should be treated with extra caution.
Thin markets (few transactions per month) produce noisier signals.
Seasonal patterns can shift over time — always combine with the price trend and market activity tabs before deciding.
            """
        )

    st.markdown("**Select a district and property type to analyse seasonal entry patterns:**")
    c1, c2 = st.columns(2)
    with c1:
        entry_district_opts = sorted(df[config.COL_DISTRICT].str.title().unique().tolist())
        # Default to the first sidebar-selected district when available
        _sidebar_district_title = sel_districts[0].title() if sel_districts else None
        _entry_district_default = (
            entry_district_opts.index(_sidebar_district_title)
            if _sidebar_district_title and _sidebar_district_title in entry_district_opts
            else 0
        )
        entry_district = st.selectbox(
            "District to Analyse",
            options=entry_district_opts,
            index=_entry_district_default,
            help="Defaults to your sidebar district selection. Change here for a standalone seasonal deep-dive.",
        )
    with c2:
        entry_type_opts = sorted(df[config.COL_PROPERTY_TYPE].unique().tolist())
        # Default to the first sidebar-selected property type when available
        _sidebar_type = sel_property_types[0] if sel_property_types else None
        _entry_type_default = (
            entry_type_opts.index(_sidebar_type)
            if _sidebar_type and _sidebar_type in entry_type_opts
            else 0
        )
        entry_type = st.selectbox(
            "Property Type to Analyse",
            options=entry_type_opts,
            index=_entry_type_default,
            format_func=lambda x: config.PROPERTY_TYPE_LABELS.get(x, x.title()),
            help="Defaults to your sidebar property type selection. Change here for a standalone seasonal deep-dive.",
        )

    df_entry = df[
        (df[config.COL_DISTRICT] == entry_district.lower()) &
        (df[config.COL_PROPERTY_TYPE] == entry_type)
    ]

    result = compute_entry_signals(df_entry)

    if not result["success"]:
        st.warning(
            f"Cannot compute seasonal signals for **{entry_district}** · "
            f"**{config.PROPERTY_TYPE_LABELS.get(entry_type, entry_type.title())}**: "
            f"{result['reason']}. "
            "Try selecting a more active district or a broader property type."
        )
    else:
        signals = result["signals"]

        if result.get("low_data_quality"):
            st.warning(
                f"⚠️ **Low data quality:** Only {result['n_months']} months of data available "
                f"(recommended minimum: {config.MIN_MONTHS_FOR_DECOMPOSITION}). "
                "With fewer than 3 full annual cycles, each month's seasonal pattern is estimated "
                "from very few data points — treat these signals with extra caution."
            )

        st.caption(
            f"Analysis based on **{result['n_transactions']:,} transactions** "
            f"across **{result['year_span']}** · {result['amplitude_note']}"
        )

        col_wheel, col_bars = st.columns([1, 1])
        with col_wheel:
            st.plotly_chart(fig_seasonality_wheel(signals), use_container_width=True)
            st.caption(
                "Polar chart: **longer bars = better time to buy** (higher entry score). "
                "Score = 100 − composite signal, so low-price / low-competition months score highest."
            )
        with col_bars:
            st.plotly_chart(fig_entry_signal_bars(signals), use_container_width=True)
            st.caption(
                "Entry score per month (0–100). **Higher = better time to buy** "
                "(lower seasonal prices + lower competition). "
                "Combines price seasonality (60% weight) and transaction volume (40% weight)."
            )

        st.plotly_chart(fig_seasonal_component(signals), use_container_width=True)
        st.caption(
            "Seasonal price component extracted from the full price series. "
            "Positive values = prices tend to be above the annual average that month. "
            "Negative = below average — historically cheaper to buy."
        )

        st.divider()
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**Historically Best Entry Months**")
            st.caption("Months where prices have consistently been below the annual average.")
            for m in result["best_months"]:
                st.markdown(f"- :green[{m}]")
        with sc2:
            st.markdown("**Historically Worst Entry Months**")
            st.caption("Months where prices have consistently been above the annual average.")
            for m in result["worst_months"]:
                st.markdown(f"- :red[{m}]")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: Trend & Outlook
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Trend & Outlook":
    monthly_all = get_monthly_median_rate(df, group_by=None, min_transactions=min_tx)

    if len(monthly_all) < config.MIN_MONTHS_FOR_DECOMPOSITION:
        st.warning(
            f"Need at least {config.MIN_MONTHS_FOR_DECOMPOSITION} months of data to run decomposition. "
            f"Current filters return {len(monthly_all)} months. "
            "Try expanding the year range or broadening district and property type selections."
        )
    else:
        series = monthly_all.set_index(config.COL_YEARMONTH)["median_rate"]

        try:
            decomp = decompose_time_series(series)
            decomp_ok = True
        except Exception as e:
            st.warning(f"Cannot run decomposition: {e}")
            decomp_ok = False

        if decomp_ok:
            # ── 1. Dual momentum gauges (current state at a glance) ──────────
            momentum_df = compute_momentum(series)
            if len(momentum_df) > 0:
                latest_mom_3m = momentum_df["mom_3m"].iloc[-1]
                latest_mom_12m = momentum_df["mom_12m"].iloc[-1] if momentum_df["mom_12m"].notna().any() else latest_mom_3m
                st.plotly_chart(fig_momentum_gauge_dual(latest_mom_3m, latest_mom_12m), use_container_width=True)
                st.caption(
                    "**3-Month** = short-term momentum (last 3M vs prior 3M). Sensitive to recent moves. "
                    "**12-Month** = trend confirmation (last 3M vs 3M one year ago). More stable signal. "
                    "Positive = prices rising. Negative = falling. Agreement between the two = stronger signal."
                )

            st.divider()

            # ── 2. Trend projection (where is it heading) ───────────────────
            proj_result = project_trend(decomp.trend, periods_ahead=config.PROJECTION_MONTHS)
            if proj_result["success"]:
                if proj_result["high_uncertainty"]:
                    st.warning(
                        "High uncertainty detected: residual variance is increasing over time. "
                        "Treat the projection with extra caution."
                    )

                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    slope = proj_result["slope_per_month"]
                    direction = "Upward" if slope > 0 else "Downward"
                    st.metric(
                        "Trend Direction",
                        direction,
                        f"AED {slope:+,.0f}/sqm per month",
                        help="Direction and rate of the underlying price trend, stripped of seasonal noise. Fit uses the most recent 30 months to reflect current trajectory.",
                    )
                with col_info2:
                    st.metric(
                        "Trend R²",
                        f"{proj_result['r_squared']:.3f}",
                        help="How well a straight line fits the recent trend. 1.0 = perfect linear trend. Below 0.7 = noisy or non-linear — treat projection cautiously.",
                    )

                st.plotly_chart(
                    fig_trend_projection(proj_result["historical"], proj_result["projection"]),
                    use_container_width=True,
                )
                st.caption(
                    f"Trend component with {config.PROJECTION_MONTHS}-month linear projection (fit on last {config.PROJECTION_LOOKBACK_MONTHS} months). "
                    "Shaded area = 95% confidence interval. "
                    "Widen the year range in the sidebar for a more reliable projection."
                )

            st.divider()

            # ── 3. Decomposition panel (methodology for analysts) ────────────
            st.plotly_chart(fig_decomposition_panel(decomp), use_container_width=True)
            st.caption(
                "Seasonal decomposition of monthly median prices. "
                "**Trend** = underlying direction with noise removed. "
                "**Seasonal Component** = the repeating annual cycle (AED/SQM above/below trend). "
                "**Residual** = unexplained variation — high residuals indicate volatile or data-thin periods."
            )

            with st.expander("Monthly Data Table (last 24 months)"):
                display_df = monthly_all.tail(24).sort_values(config.COL_YEARMONTH, ascending=False).copy()
                display_df["median_rate"] = display_df["median_rate"].round(0).astype(int)
                display_df[config.COL_YEARMONTH] = display_df[config.COL_YEARMONTH].dt.strftime("%b %Y")
                display_df.columns = ["Month", "Median Rate (AED/SQM)", "Transactions"]
                st.dataframe(display_df, use_container_width=True)
                st.download_button(
                    "Download table (CSV)",
                    data=display_df.to_csv(index=False).encode("utf-8"),
                    file_name="monthly_median_rates.csv",
                    mime="text/csv",
                )

            st.caption(
                "Disclaimer: Projections are based on linear extrapolation of the trend component "
                "extracted via seasonal decomposition. They assume no structural market changes. "
                "Do not interpret projections beyond 6 months as reliable forecasts."
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: Market Comparison (Property Finder asking prices vs actuals)
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Asking vs Actual":
    try:
        from pf_scraper import fetch_propertyfinder, load_pf_history, save_pf_snapshot, get_cache_info
        from pf_processor import (
            normalise_pf_listings, build_asking_vs_actual,
            build_mom_comparison, get_snapshot_metadata, get_pf_snapshot_df,
        )
        _pf_available = True
    except ImportError:
        _pf_available = False

    if not _pf_available:
        st.info(
            "**Asking vs Actual** requires the Property Finder scraper module (`pf_scraper.py` and `pf_processor.py`). "
            "These files were not found in the project directory. "
            "Add them to enable live asking price comparison against transaction data."
        )
        st.stop()

    st.info(
        "**How to use:** Click **Update PF Listings** to pull the latest asking prices from "
        "Property Finder. Each snapshot is saved automatically. Once you have two or more "
        "snapshots, the MoM tracking and alert sections activate."
    )

    # ── Section A: Data Controls ─────────────────────────────────────────────
    st.subheader("Data Controls")
    ctrl_col1, ctrl_col2 = st.columns([2, 2])

    with ctrl_col1:
        cache_info = get_cache_info()
        if cache_info["exists"]:
            last_ts = _dt.fromtimestamp(cache_info["ts"]).strftime("%b %d, %Y %H:%M")
            btn_label = f"Update PF Listings  ·  Last cached: {last_ts} · {cache_info['count']:,} listings"
        else:
            btn_label = "Update PF Listings  ·  No cache yet"

        do_update = st.button(btn_label, type="primary", use_container_width=True)

        if do_update:
            # Check if today's snapshot already exists
            _history_check = load_pf_history()
            _today_key = _dt.now().strftime("%Y-%m-%d")
            _existing_keys = {s.get("month") for s in _history_check.get("snapshots", [])}
            _already_saved = _today_key in _existing_keys

            if _already_saved and not st.session_state.get("_pf_force_rescrape"):
                st.warning(
                    f"A snapshot for **{_today_key}** already exists. "
                    "Click below to force a re-scrape."
                )
                if st.button("Force re-scrape today's snapshot"):
                    st.session_state["_pf_force_rescrape"] = True
                    st.rerun()
            else:
                st.session_state.pop("_pf_force_rescrape", None)
                force = _already_saved  # bypass cache only if re-scraping same day
                with st.spinner("Scraping Property Finder… this may take 60–90 seconds."):
                    _listings = fetch_propertyfinder(
                        cutoff_days=config.PF_CUTOFF_DAYS,
                        max_pages=config.PF_MAX_PAGES,
                        rate_sleep=config.PF_RATE_SLEEP,
                        force=force,
                    )
                if _listings:
                    _snap_key = save_pf_snapshot(_listings, force=_already_saved)
                    _verb = "Updated" if _already_saved else "Saved"
                    st.success(f"{_verb} {len(_listings):,} listings as snapshot **{_snap_key}**.")
                    st.rerun()
                else:
                    st.error("No listings returned. Check your internet connection or try again later.")

    with ctrl_col2:
        st.caption(
            f"Transaction data: **{len(df_raw):,} rows** · "
            f"Latest: **{df_raw[config.COL_DATE].max().strftime('%b %Y')}**"
        )
        if "df_raw_active" in st.session_state:
            st.info("Using merged dataset from sidebar upload. To revert, use **Update Transaction Data** in the sidebar.")
        else:
            st.caption("To update transaction data, use **Update Transaction Data** in the sidebar — all tabs refresh automatically.")

    # Tab 5 always uses the session-state-aware df_raw (set at top of script)
    _actual_raw = df_raw

    # ── Load PF history ───────────────────────────────────────────────────────
    pf_history = load_pf_history()
    snap_meta = get_snapshot_metadata(pf_history)

    # Load current cache listings for immediate use (even without a saved snapshot)
    _cache_listings = []
    if cache_info["exists"]:
        try:
            import json as _json
            from pathlib import Path as _Path
            _cache_raw = _json.loads((_Path(__file__).parent / "pf_cache.json").read_text(encoding="utf-8"))
            _cache_listings = _cache_raw.get("listings", [])
        except Exception:
            pass

    pf_df_current = normalise_pf_listings(_cache_listings, cutoff_days=config.PF_CUTOFF_DAYS)

    if pf_df_current.empty and not snap_meta:
        st.warning(
            "No Property Finder data available yet. "
            "Click **Update PF Listings** to fetch the first snapshot."
        )
        st.stop()

    st.divider()

    # ── Section B: MoM Alerts ────────────────────────────────────────────────
    st.subheader("Month-on-Month Asking Price Alerts")

    if len(snap_meta) >= 2:
        mom_df = build_mom_comparison(pf_history, min_listings=config.PF_MIN_LISTINGS)
        alerts = mom_df[mom_df["alert"]] if not mom_df.empty else pd.DataFrame()

        prev_key = snap_meta[1]["key"] if len(snap_meta) > 1 else "—"
        curr_key = snap_meta[0]["key"]
        st.caption(
            f"Comparing **{curr_key}** (current) vs **{prev_key}** (previous) "
            f"· same project, type & beds · threshold: >{abs(config.PF_ALERT_DROP_PCT):.0f}% drop"
        )

        if not alerts.empty:
            st.error(f"**{len(alerts)} asking price drop(s) detected:**")
            for _, row in alerts.iterrows():
                prev_med = row["prev_median"]
                curr_med = row["curr_median"]
                chg = row["mom_change_pct"]
                label = (
                    f"{row['community']} · {row['type'].title()} · {row['beds']} "
                    f"— {chg:+.1f}%  "
                    f"(AED {prev_med:,.0f} → AED {curr_med:,.0f} /sqm)"
                )
                with st.expander(label, expanded=False):
                    col_prev, col_curr = st.columns(2)

                    def _render_listings(col, snap_key, median_val, n_count, samples):
                        with col:
                            st.markdown(
                                f"**{snap_key}** — {int(n_count)} listing(s), "
                                f"median **AED {median_val:,.0f}/sqm**"
                            )
                            if samples:
                                for listing in samples:
                                    area_str = f"{listing['area_sqm']:.0f} sqm" if listing.get("area_sqm") else "—"
                                    price_str = f"AED {listing['price']:,.0f}" if listing.get("price") else "—"
                                    rate_str = f"AED {listing['price_per_sqm']:,.0f}/sqm" if listing.get("price_per_sqm") else "—"
                                    title = listing.get("title") or "—"
                                    url = listing.get("url", "")
                                    link = f" [↗]({url})" if url else ""
                                    st.markdown(f"- **{title}**{link}  \n  {area_str} · {price_str} · {rate_str}")
                            else:
                                st.caption("No sample listings available.")

                    _render_listings(col_prev, prev_key, prev_med, row.get("n_prev", 0), row.get("prev_samples", []))
                    _render_listings(col_curr, curr_key, curr_med, row.get("n_curr", 0), row.get("curr_samples", []))
        else:
            st.success("No significant asking price drops detected across tracked segments.")
    elif len(snap_meta) == 1:
        st.info(
            f"One snapshot saved ({snap_meta[0]['key']}). "
            "Collect a second snapshot next week to enable MoM tracking."
        )
    else:
        st.info("Save your first snapshot to begin tracking.")

    st.divider()

    # ── Section C: Snapshot Selector ─────────────────────────────────────────
    st.subheader("Snapshot to Compare Against Actuals")

    if snap_meta:
        snap_options = {s["key"]: f"{s['key']}  ({s['count']:,} listings)" for s in snap_meta}
        selected_snap_key = st.selectbox(
            "Snapshot",
            options=list(snap_options.keys()),
            format_func=lambda k: snap_options[k],
            index=0,
            help="Select which snapshot to compare against actual transaction prices.",
        )
        pf_df_selected = get_pf_snapshot_df(pf_history, selected_snap_key)
    else:
        st.caption("Using current cache data (no saved snapshot yet).")
        pf_df_selected = pf_df_current

    if pf_df_selected.empty:
        st.warning("Selected snapshot is empty or could not be parsed.")
        st.stop()

    st.divider()

    # ── Section D: Asking vs Actual Price Chart ───────────────────────────────
    st.subheader("Asking vs Actual Price per SQM")

    # Filters for this section
    d_col1, d_col2, d_col3 = st.columns([3, 2, 1])
    with d_col1:
        pf_districts_available = sorted(pf_df_selected["pf_district"].dropna().unique().tolist())
        sel_pf_districts = st.multiselect(
            "Filter by district",
            options=pf_districts_available,
            default=[],
            placeholder="All districts",
            key="pf_district_filter",
        )
    with d_col2:
        pf_types_available = sorted(pf_df_selected["type"].dropna().unique().tolist())
        sel_pf_type = st.selectbox(
            "Property type",
            options=["All"] + [t.title() for t in pf_types_available],
            index=0,
            key="pf_type_filter",
        )
    with d_col3:
        show_pct_labels = st.checkbox("Show premium %", value=True, key="pf_show_pct")

    # Apply filters
    pf_filtered = pf_df_selected.copy()
    if sel_pf_districts:
        pf_filtered = pf_filtered[pf_filtered["pf_district"].isin(sel_pf_districts)]
    if sel_pf_type != "All":
        pf_filtered = pf_filtered[pf_filtered["type"] == sel_pf_type.lower()]

    comparison_df = build_asking_vs_actual(pf_filtered, _actual_raw, min_listings=config.PF_MIN_LISTINGS)

    if comparison_df.empty:
        st.info(
            f"Not enough data for the current filters (min {config.PF_MIN_LISTINGS} listings per segment). "
            "Try removing district or type filters."
        )
    else:
        # Build grouped bar chart
        has_actual = comparison_df["actual_median"].notna().any()
        segments = (
            comparison_df["district"].str.title() + " · " +
            comparison_df["type"].str.title() + " · " +
            comparison_df["beds"]
        )

        fig_cmp = go.Figure()
        fig_cmp.add_trace(go.Bar(
            name="Asking (PF)",
            x=segments,
            y=comparison_df["asking_median"],
            marker_color=config.SALE_TYPE_COLORS["off-plan"],
            text=comparison_df["asking_median"].apply(lambda v: f"AED {v:,.0f}" if v else ""),
            textposition="outside",
        ))
        if has_actual:
            fig_cmp.add_trace(go.Bar(
                name="Actual (transactions)",
                x=segments,
                y=comparison_df["actual_median"],
                marker_color=config.SALE_TYPE_COLORS["ready"],
                text=comparison_df["actual_median"].apply(lambda v: f"AED {v:,.0f}" if pd.notna(v) else "N/A"),
                textposition="outside",
            ))

        if show_pct_labels and has_actual:
            for i, row in comparison_df.iterrows():
                if pd.notna(row["premium_pct"]):
                    color = "#e74c3c" if row["premium_pct"] > 0 else "#27ae60"
                    sign = "+" if row["premium_pct"] > 0 else ""
                    fig_cmp.add_annotation(
                        x=segments.iloc[i],
                        y=max(
                            row["asking_median"] or 0,
                            row["actual_median"] if pd.notna(row["actual_median"]) else 0,
                        ) * 1.15,
                        text=f"<b>{sign}{row['premium_pct']:.1f}%</b>",
                        showarrow=False,
                        font=dict(size=11, color=color),
                    )

        fig_cmp.update_layout(
            barmode="group",
            xaxis_title="Segment",
            yaxis_title="Median Price (AED/SQM)",
            legend=dict(orientation="h", y=1.08),
            margin=dict(t=60, b=120),
            height=500,
            xaxis_tickangle=-35,
        )
        st.plotly_chart(fig_cmp, use_container_width=True)
        st.caption(
            "Purple = median asking price/sqm from Property Finder. "
            "Teal = median actual transaction price/sqm (last 3 months of CSV data). "
            "Percentage label = premium (red) or discount (green) vs actuals."
        )

        # Unmatched segments note
        _unmatched = comparison_df[comparison_df["actual_median"].isna()]
        if not _unmatched.empty:
            _names = ", ".join(
                (_unmatched["district"].str.title() + " · " + _unmatched["type"].str.title())
                .unique()[:5]
            )
            st.caption(
                f"ℹ️ {len(_unmatched)} segment(s) have no actual transaction match "
                f"(district not yet in CSV): {_names}."
            )

        # Download comparison table
        _dl_df = comparison_df[["district", "type", "beds", "asking_median", "actual_median", "premium_pct", "n_asking", "n_actual"]].copy()
        _dl_df.columns = ["District", "Type", "Beds", "Asking Median (AED/SQM)", "Actual Median (AED/SQM)", "Premium %", "# PF Listings", "# Transactions"]
        st.download_button(
            "Download comparison table (CSV)",
            data=_dl_df.to_csv(index=False).encode("utf-8"),
            file_name="pf_vs_actual_comparison.csv",
            mime="text/csv",
        )

    st.divider()

    # ── Section E: Premium/Discount Heatmap ──────────────────────────────────
    st.subheader("Premium / Discount Heatmap")

    if not comparison_df.empty and comparison_df["premium_pct"].notna().any():
        pivot = comparison_df.pivot_table(
            index="district",
            columns="beds",
            values="premium_pct",
            aggfunc="mean",
        )
        pivot.index = pivot.index.str.title()

        # Color scale: green (discount) → white → red (premium)
        fig_heat = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale=[
                [0.0, "#27ae60"],
                [0.5, "#f5f5f5"],
                [1.0, "#e74c3c"],
            ],
            zmid=0,
            text=[[f"{v:+.1f}%" if pd.notna(v) else "N/A" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            colorbar=dict(title="Premium %"),
        ))
        fig_heat.update_layout(
            xaxis_title="Bedroom type",
            yaxis_title="District",
            height=max(300, len(pivot) * 40 + 100),
            margin=dict(t=40),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
        st.caption(
            "Green = asking price **below** actual market (potential buy signal). "
            "Red = asking price **above** actual market (premium). "
            "Blank = fewer than the minimum listing threshold."
        )
    else:
        st.info("Not enough matched data to render the heatmap.")

    st.divider()

    # ── Section F: MoM Asking Price Trend ────────────────────────────────────
    st.subheader("MoM Asking Price Trend")

    if len(snap_meta) < 2:
        st.info("Collect at least two snapshots to view MoM asking price trends.")
    else:
        # Build time-series from all snapshots
        trend_rows = []
        for snap in pf_history.get("snapshots", []):
            # Pass reference_date so old snapshots are not filtered out by the 30-day cutoff
            _snap_ts = snap.get("collected_at", "")
            _snap_ref = None
            if _snap_ts:
                try:
                    from datetime import datetime as _datetime_cls, timezone as _tz
                    _snap_ref = _datetime_cls.fromisoformat(_snap_ts.replace("Z", "+00:00"))
                    if _snap_ref.tzinfo is None:
                        _snap_ref = _snap_ref.replace(tzinfo=_tz.utc)
                except Exception:
                    pass
            _sdf = normalise_pf_listings(snap.get("listings", []), reference_date=_snap_ref)
            if _sdf.empty:
                continue
            _agg = (
                _sdf.groupby(["district", "type"])["price_per_sqm"]
                .median()
                .reset_index()
            )
            _agg["snap_date"] = snap.get("month", "")
            trend_rows.append(_agg)

        if trend_rows:
            trend_df = pd.concat(trend_rows, ignore_index=True)
            trend_df["segment"] = trend_df["district"].str.title() + " · " + trend_df["type"].str.title()

            # Filter to segments with data in ≥2 snapshots
            seg_counts = trend_df.groupby("segment")["snap_date"].nunique()
            valid_segs = seg_counts[seg_counts >= 2].index
            trend_df = trend_df[trend_df["segment"].isin(valid_segs)]

            if trend_df.empty:
                st.info("Not enough multi-snapshot data to render the trend chart yet.")
            else:
                fig_trend = go.Figure()
                for seg, grp in trend_df.groupby("segment"):
                    grp = grp.sort_values("snap_date")
                    fig_trend.add_trace(go.Scatter(
                        x=grp["snap_date"],
                        y=grp["price_per_sqm"],
                        mode="lines+markers",
                        name=seg,
                    ))

                fig_trend.update_layout(
                    xaxis_title="Snapshot date",
                    yaxis_title="Median Asking Price (AED/SQM)",
                    legend=dict(orientation="h", y=-0.3),
                    height=450,
                    margin=dict(t=40, b=160),
                )
                st.plotly_chart(fig_trend, use_container_width=True)
                st.caption(
                    "Median asking price per sqm per district+type across all saved snapshots. "
                    "Only segments with data in at least two snapshots are shown."
                )

    st.divider()

    # ── Section G: Individual Listings ────────────────────────────────────────
    st.subheader("Individual Listings")
    with st.expander("Browse current PF listings", expanded=False):
        if pf_df_selected.empty:
            st.info("No listings available.")
        else:
            # Quick filters
            _gl_col1, _gl_col2, _gl_col3 = st.columns(3)
            with _gl_col1:
                _gl_districts = sorted(pf_df_selected["pf_district"].dropna().unique().tolist())
                _gl_sel_district = st.multiselect(
                    "District", options=_gl_districts, default=[], key="gl_district",
                    placeholder="All",
                )
            with _gl_col2:
                _gl_types = sorted(pf_df_selected["type"].dropna().unique().tolist())
                _gl_sel_type = st.multiselect(
                    "Type", options=[t.title() for t in _gl_types], default=[], key="gl_type",
                    placeholder="All",
                )
            with _gl_col3:
                _gl_beds = sorted(pf_df_selected["beds"].dropna().unique().tolist())
                _gl_sel_beds = st.multiselect(
                    "Beds", options=_gl_beds, default=[], key="gl_beds",
                    placeholder="All",
                )

            _listings_view = pf_df_selected.copy()
            if _gl_sel_district:
                _listings_view = _listings_view[_listings_view["pf_district"].isin(_gl_sel_district)]
            if _gl_sel_type:
                _listings_view = _listings_view[_listings_view["type"].isin([t.lower() for t in _gl_sel_type])]
            if _gl_sel_beds:
                _listings_view = _listings_view[_listings_view["beds"].isin(_gl_sel_beds)]

            _listings_view = _listings_view.sort_values("price_per_sqm").reset_index(drop=True)

            # Display columns
            _show_cols = {
                "pf_district": "District",
                "type": "Type",
                "beds": "Beds",
                "price": "Price (AED)",
                "area_sqm": "Area (SQM)",
                "price_per_sqm": "Price/SQM",
                "sale_type": "Sale Type",
                "url": "Link",
            }
            _display = _listings_view[[c for c in _show_cols if c in _listings_view.columns]].rename(columns=_show_cols)
            if "Price (AED)" in _display.columns:
                _display["Price (AED)"] = _display["Price (AED)"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")
            if "Price/SQM" in _display.columns:
                _display["Price/SQM"] = _display["Price/SQM"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

            st.dataframe(
                _display,
                use_container_width=True,
                column_config={"Link": st.column_config.LinkColumn("Link")},
                hide_index=True,
            )
            st.caption(f"{len(_listings_view):,} listings shown.")
            st.download_button(
                "Download listings (CSV)",
                data=_display.to_csv(index=False).encode("utf-8"),
                file_name="pf_listings.csv",
                mime="text/csv",
                key="dl_listings",
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB: Asking Price Analysis
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Asking Price Analysis":
    try:
        from pf_scraper import load_pf_history as _load_pf_apa
        from pf_processor import (
            normalise_pf_listings as _norm_pf_apa,
            build_asking_trend_series, build_asking_vs_actual_overlay,
            build_asking_recommendations, get_snapshot_metadata as _get_snap_meta_apa,
        )
        _apa_available = True
    except ImportError:
        _apa_available = False

    if not _apa_available:
        st.info(
            "**Asking Price Analysis** requires `pf_scraper.py` and `pf_processor.py`. "
            "Add them to enable asking price trend analysis."
        )
        st.stop()

    _apa_history = _load_pf_apa()
    _apa_snap_meta = _get_snap_meta_apa(_apa_history)

    if not _apa_snap_meta:
        st.warning(
            "No Property Finder snapshots found. Use the **Asking vs Actual** tab to "
            "collect your first snapshot, then return here for trend analysis."
        )
        st.stop()

    # ── Section A: Snapshot Time-Range Selector (R1, R11g) ────────────────────
    _all_snap_keys = sorted([s["key"] for s in _apa_snap_meta])

    _range_preset = st.radio(
        "Time range",
        ["Last 7 days", "Last 30 days", "Last 90 days", "All", "Custom"],
        index=1,
        horizontal=True,
        key="pf_trend_range_preset",
    )

    _today = _dt.now()
    if _range_preset == "Last 7 days":
        _snap_start = (_today - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        _snap_end = None
    elif _range_preset == "Last 30 days":
        _snap_start = (_today - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        _snap_end = None
    elif _range_preset == "Last 90 days":
        _snap_start = (_today - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        _snap_end = None
    elif _range_preset == "All":
        _snap_start = None
        _snap_end = None
    else:
        _cust_col1, _cust_col2 = st.columns(2)
        with _cust_col1:
            _snap_start = st.date_input(
                "From", value=pd.to_datetime(_all_snap_keys[0]),
                key="pf_trend_date_start",
            ).strftime("%Y-%m-%d")
        with _cust_col2:
            _snap_end = st.date_input(
                "To", value=pd.to_datetime(_all_snap_keys[-1]),
                key="pf_trend_date_end",
            ).strftime("%Y-%m-%d")

    # Filter snap keys for subtitle
    _filtered_keys = [
        k for k in _all_snap_keys
        if (not _snap_start or k >= _snap_start) and (not _snap_end or k <= _snap_end)
    ]
    _n_snaps = len(_filtered_keys)
    _range_label_start = _filtered_keys[0] if _filtered_keys else "—"
    _range_label_end = _filtered_keys[-1] if _filtered_keys else "—"
    st.caption(
        f"Showing data from **{_range_label_start}** to **{_range_label_end}** "
        f"(**{_n_snaps}** snapshot{'s' if _n_snaps != 1 else ''})"
    )

    if _n_snaps < config.PF_TREND_MIN_SNAPSHOTS:
        st.info(
            f"Need at least {config.PF_TREND_MIN_SNAPSHOTS} snapshots in the selected range. "
            f"Currently have {_n_snaps}. Broaden the time range or collect more snapshots."
        )
        st.stop()

    # ── Build trend series (R4) ───────────────────────────────────────────────
    _trend_series = build_asking_trend_series(
        _apa_history,
        snap_start=_snap_start,
        snap_end=_snap_end,
        min_snapshots=config.PF_TREND_MIN_SNAPSHOTS,
    )

    if _trend_series.empty:
        st.info(
            "Not enough multi-snapshot data for the selected range. "
            "Try selecting 'All' or collecting more snapshots."
        )
        st.stop()

    # ── Section B: Cascading Filters (R3, R11c) ──────────────────────────────
    st.divider()

    _fc1, _fc2, _fc3, _fc4 = st.columns(4)

    # District filter
    _avail_districts = sorted(_trend_series["district"].str.title().unique().tolist())
    with _fc1:
        _sel_districts_apa = st.multiselect(
            f"District ({len(_avail_districts)})",
            options=_avail_districts,
            default=[],
            placeholder="All districts",
            key="pf_trend_district",
        )

    # Apply district filter for cascading
    _ts_filtered = _trend_series.copy()
    if _sel_districts_apa:
        _ts_filtered = _ts_filtered[_ts_filtered["district"].str.title().isin(_sel_districts_apa)]

    # Type filter
    _avail_types = sorted(_ts_filtered["type"].unique().tolist())
    with _fc2:
        _default_type_idx = _avail_types.index("apartment") if "apartment" in _avail_types else 0
        _sel_type_apa = st.selectbox(
            "Property Type",
            options=_avail_types,
            index=_default_type_idx,
            format_func=lambda t: config.PROPERTY_TYPE_LABELS.get(t, t.title()),
            key="pf_trend_type",
        )

    _ts_filtered = _ts_filtered[_ts_filtered["type"] == _sel_type_apa]

    # Beds filter
    _avail_beds = sorted(_ts_filtered["beds"].unique().tolist())
    with _fc3:
        _n_beds = _ts_filtered.groupby("beds")["snap_date"].count()
        _beds_labels = {b: f"{b} ({_n_beds.get(b, 0)})" for b in _avail_beds}
        _sel_beds_apa = st.multiselect(
            f"Layout ({len(_avail_beds)})",
            options=_avail_beds,
            default=[],
            placeholder="All layouts",
            format_func=lambda b: _beds_labels.get(b, b),
            key="pf_trend_beds",
        )

    if _sel_beds_apa:
        _ts_filtered = _ts_filtered[_ts_filtered["beds"].isin(_sel_beds_apa)]

    # Community filter
    _avail_communities = sorted(_ts_filtered["community"].unique().tolist())
    with _fc4:
        _sel_communities_apa = st.multiselect(
            f"Project ({len(_avail_communities)})",
            options=_avail_communities,
            default=[],
            placeholder="All projects",
            key="pf_trend_community",
        )

    if _sel_communities_apa:
        _ts_filtered = _ts_filtered[_ts_filtered["community"].isin(_sel_communities_apa)]

    # Build segment label for charts
    _ts_filtered = _ts_filtered.copy()
    _ts_filtered["segment"] = (
        _ts_filtered["district"].str.title() + " · " +
        _ts_filtered["type"].str.title() + " · " +
        _ts_filtered["beds"]
    )
    if _sel_communities_apa:
        _ts_filtered["segment"] = _ts_filtered["community"] + " · " + _ts_filtered["beds"]

    # ── Section C: KPI Cards (R11b) ──────────────────────────────────────────
    st.divider()

    if _ts_filtered.empty:
        st.info("Not enough listings for the selected filters — try broadening your filters.")
        st.stop()

    _latest_snap = _ts_filtered["snap_date"].max()
    _latest_data = _ts_filtered[_ts_filtered["snap_date"] == _latest_snap]
    _kpi_median = _latest_data["median_asking_rate"].median()
    _kpi_listings = int(_latest_data["n_listings"].sum())

    # Average MoM change across segments in latest snapshot
    _latest_pop = _latest_data["pct_change_pop"].dropna()
    _kpi_mom = _latest_pop.median() if len(_latest_pop) > 0 else None

    # Average cumulative change
    _latest_cum = _latest_data["pct_change_cumulative"].dropna()
    _kpi_cum = _latest_cum.median() if len(_latest_cum) > 0 else None

    _k1, _k2, _k3, _k4 = st.columns(4)
    with _k1:
        st.metric(
            "Median Asking Price",
            f"AED {_kpi_median:,.0f}/sqm" if pd.notna(_kpi_median) else "—",
            help="Median asking price per sqm across all segments in the latest snapshot.",
        )
    with _k2:
        if _kpi_mom is not None and pd.notna(_kpi_mom):
            st.metric(
                "MoM Change",
                f"{_kpi_mom:+.1f}%",
                delta=f"{_kpi_mom:+.1f}%",
                delta_color="inverse",
                help="Median period-over-period change across filtered segments.",
            )
        else:
            st.metric("MoM Change", "—")
    with _k3:
        st.metric(
            "Active Listings",
            f"{_kpi_listings:,}" if _kpi_listings else "—",
            help="Total listings in the latest snapshot matching current filters.",
        )
    with _k4:
        if _kpi_cum is not None and pd.notna(_kpi_cum):
            st.metric(
                "Cumulative Change",
                f"{_kpi_cum:+.1f}%",
                delta=f"{_kpi_cum:+.1f}%",
                delta_color="inverse",
                help="Median cumulative change from first snapshot in range.",
            )
        else:
            st.metric("Cumulative Change", "—")

    st.divider()

    # ── Section D: Trend Charts (R6, R11d, R11e) ─────────────────────────────

    # Chart A: Asking Price Trend Line
    st.plotly_chart(
        fig_asking_trend_line(_ts_filtered, segment_col="segment"),
        use_container_width=True,
    )
    # Dynamic caption (R11d)
    _n_segments = _ts_filtered["segment"].nunique()
    _trend_direction = "dropped" if (_kpi_mom is not None and _kpi_mom < 0) else "risen"
    if _kpi_mom is not None and pd.notna(_kpi_mom):
        st.caption(
            f"Tracking **{_n_segments}** segment(s). "
            f"Asking prices have {_trend_direction} **{abs(_kpi_mom):.1f}%** in the latest snapshot period. "
            f"{_kpi_listings:,} listings match the current filters."
        )
    else:
        st.caption(
            f"Tracking **{_n_segments}** segment(s) across **{_n_snaps}** snapshots. "
            f"{_kpi_listings:,} listings match the current filters."
        )

    # Charts C & D side by side: % Change Bar + Cumulative Line
    _chart_col1, _chart_col2 = st.columns(2)
    with _chart_col1:
        st.plotly_chart(
            fig_asking_pct_change_bar(_ts_filtered, segment_col="segment"),
            use_container_width=True,
        )
        _drops = _ts_filtered[_ts_filtered["pct_change_pop"] < 0]
        if not _drops.empty:
            _avg_drop = _drops["pct_change_pop"].median()
            st.caption(f"Average price drop when declining: **{_avg_drop:.1f}%** — green bars signal buyer leverage.")
        else:
            st.caption("No price drops detected in the selected range — sellers holding firm.")

    with _chart_col2:
        st.plotly_chart(
            fig_asking_cumulative_line(_ts_filtered, segment_col="segment"),
            use_container_width=True,
        )
        if _kpi_cum is not None and pd.notna(_kpi_cum):
            _cum_label = "appreciated" if _kpi_cum > 0 else "declined"
            st.caption(
                f"Asking prices have {_cum_label} **{abs(_kpi_cum):.1f}%** since first tracked snapshot."
            )
        else:
            st.caption("Cumulative change tracks total movement from the first snapshot in range.")

    st.divider()

    # ── Section E: Asking vs Actual Overlay (R5) ─────────────────────────────
    st.subheader("Asking vs Actual Transaction Prices")

    _overlay_df = build_asking_vs_actual_overlay(_ts_filtered, df_raw)

    if _overlay_df.empty or _overlay_df["median_actual_rate"].isna().all():
        st.info(
            "Not enough actual transaction data to overlay for the selected filters. "
            "This can happen when the PF district name doesn't match the transaction data, "
            "or when no recent transactions exist for this segment."
        )
    else:
        # Build one overlay chart per segment (full width per R11h)
        _overlay_segments = _overlay_df["segment"].unique() if "segment" in _overlay_df.columns else []
        if "segment" not in _overlay_df.columns:
            _overlay_df["segment"] = (
                _overlay_df["district"].str.title() + " · " +
                _overlay_df["type"].str.title() + " · " +
                _overlay_df["beds"]
            )
            _overlay_segments = _overlay_df["segment"].unique()

        for _seg in sorted(_overlay_segments)[:5]:  # Limit to top 5 for performance
            _seg_data = _overlay_df[_overlay_df["segment"] == _seg].copy()
            if _seg_data["median_actual_rate"].notna().any():
                st.plotly_chart(
                    fig_asking_vs_actual_trend(_seg_data, segment_label=_seg),
                    use_container_width=True,
                )
                _last_row = _seg_data.sort_values("snap_date").iloc[-1]
                _prem = _last_row.get("premium_pct")
                if pd.notna(_prem):
                    _prem_word = "above" if _prem > 0 else "below"
                    _prem_color = "red" if _prem > 0 else "green"
                    st.caption(
                        f"Asking price is **{abs(_prem):.1f}%** {_prem_word} actual transaction prices "
                        f"— {'sellers pricing aggressively' if _prem > 5 else 'close to market' if abs(_prem) <= 5 else 'potential buying opportunity'}."
                    )

    st.divider()

    # ── Section F: Investment Signals (R8, R11b) ─────────────────────────────
    with st.expander("Investment Signals", expanded=True):
        _recs = build_asking_recommendations(_overlay_df if not _overlay_df.empty else _ts_filtered)

        if _recs.empty:
            st.info("Insufficient data for recommendations — broaden filters or collect more snapshots.")
        else:
            for _, _rec in _recs.iterrows():
                _seg_label = f"{_rec['district'].title()} · {_rec['type'].title()} · {_rec['beds']}"
                if _rec.get("community"):
                    _seg_label = f"{_rec['community']} · {_rec['beds']}"

                if _rec["signal_type"] == "buying_opportunity":
                    st.success(f"**{_seg_label}** — {_rec['detail_text']}")
                elif _rec["signal_type"] == "below_market":
                    st.success(f"**{_seg_label}** — {_rec['detail_text']}")
                elif _rec["signal_type"] == "momentum_premium":
                    st.warning(f"**{_seg_label}** — {_rec['detail_text']}")

    st.divider()

    # ── Section G: Drill-Down Detail (R7) ────────────────────────────────────
    with st.expander("View underlying data"):
        if _ts_filtered.empty:
            st.info("No data available for the current filters.")
        else:
            # Summary stats per snapshot
            st.markdown("**Summary Statistics per Snapshot**")
            _summary = (
                _ts_filtered.groupby("snap_date")["median_asking_rate"]
                .agg(["median", "count", "min", "max", lambda x: x.quantile(0.75) - x.quantile(0.25)])
                .reset_index()
            )
            _summary.columns = ["Snapshot", "Median (AED/sqm)", "Segments", "Min", "Max", "IQR"]
            for _col in ["Median (AED/sqm)", "Min", "Max", "IQR"]:
                _summary[_col] = _summary[_col].apply(lambda v: f"AED {v:,.0f}" if pd.notna(v) else "—")
            st.dataframe(_summary, use_container_width=True, hide_index=True)

            # Raw trend data table
            st.markdown("**Detailed Trend Data**")
            _detail_cols = ["snap_date", "district", "type", "beds", "community",
                           "median_asking_rate", "n_listings", "pct_change_pop", "pct_change_cumulative"]
            _detail = _ts_filtered[[c for c in _detail_cols if c in _ts_filtered.columns]].copy()
            _detail = _detail.sort_values(["snap_date", "district", "type", "beds"]).reset_index(drop=True)
            _detail_display = _detail.rename(columns={
                "snap_date": "Snapshot",
                "district": "District",
                "type": "Type",
                "beds": "Beds",
                "community": "Project",
                "median_asking_rate": "Median (AED/sqm)",
                "n_listings": "Listings",
                "pct_change_pop": "MoM %",
                "pct_change_cumulative": "Cumulative %",
            })
            if "Median (AED/sqm)" in _detail_display.columns:
                _detail_display["Median (AED/sqm)"] = _detail_display["Median (AED/sqm)"].apply(
                    lambda v: f"{v:,.0f}" if pd.notna(v) else "—"
                )
            if "District" in _detail_display.columns:
                _detail_display["District"] = _detail_display["District"].str.title()
            if "Type" in _detail_display.columns:
                _detail_display["Type"] = _detail_display["Type"].str.title()
            for _pct_col in ["MoM %", "Cumulative %"]:
                if _pct_col in _detail_display.columns:
                    _detail_display[_pct_col] = _detail_display[_pct_col].apply(
                        lambda v: f"{v:+.1f}%" if pd.notna(v) else "—"
                    )
            st.dataframe(_detail_display, use_container_width=True, hide_index=True)

            st.download_button(
                "Download trend data (CSV)",
                data=_detail.to_csv(index=False).encode("utf-8"),
                file_name="asking_price_analysis.csv",
                mime="text/csv",
                key="pf_trend_download",
            )

            # Actual transaction comparables
            if not _overlay_df.empty and _overlay_df["median_actual_rate"].notna().any():
                st.markdown("**Actual Transaction Comparables**")
                _act_cols = ["snap_date", "district", "type", "beds",
                            "median_asking_rate", "median_actual_rate", "premium_pct"]
                _act_detail = _overlay_df[[c for c in _act_cols if c in _overlay_df.columns]].dropna(subset=["median_actual_rate"])
                if not _act_detail.empty:
                    _act_disp = _act_detail.copy()
                    _act_disp["district"] = _act_disp["district"].str.title()
                    _act_disp["type"] = _act_disp["type"].str.title()
                    for _mc in ["median_asking_rate", "median_actual_rate"]:
                        if _mc in _act_disp.columns:
                            _act_disp[_mc] = _act_disp[_mc].apply(lambda v: f"AED {v:,.0f}" if pd.notna(v) else "—")
                    if "premium_pct" in _act_disp.columns:
                        _act_disp["premium_pct"] = _act_disp["premium_pct"].apply(
                            lambda v: f"{v:+.1f}%" if pd.notna(v) else "—"
                        )
                    _act_disp.columns = ["Snapshot", "District", "Type", "Beds",
                                        "Asking (AED/sqm)", "Actual (AED/sqm)", "Premium %"]
                    st.dataframe(_act_disp, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7: Project Intelligence
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Project Intelligence":
    st.info(
        "**Project Intelligence** answers: which specific projects are undervalued vs their district, "
        "and are their prices rising or falling? Use the screener to find opportunities, then drill "
        "into a project for its full price history and volume trend."
    )

    # ── Section A: Screener filters ──────────────────────────────────────────
    st.subheader("Section A — Project Screener")

    sa_col1, sa_col2, sa_col3 = st.columns([2, 2, 1])
    with sa_col1:
        screener_districts = sorted(df[config.COL_DISTRICT].str.title().unique().tolist())
        sel_screener_districts = st.multiselect(
            "Filter by district",
            options=screener_districts,
            default=[],
            placeholder="All districts",
            key="pi_district_filter",
        )
    with sa_col2:
        screener_types = sorted(df[config.COL_PROPERTY_TYPE].unique().tolist())
        sel_screener_types = st.multiselect(
            "Filter by property type",
            options=screener_types,
            default=[],
            format_func=lambda x: config.PROPERTY_TYPE_LABELS.get(x, x.title()),
            placeholder="All property types",
            key="pi_type_filter",
        )
    with sa_col3:
        screener_min_sales = st.number_input(
            "Min 12M sales",
            min_value=1, max_value=200, value=10, step=5,
            key="pi_min_sales",
            help="Only show projects with at least this many transactions in the last 12 months.",
        )

    # Build screener on globally-filtered df
    screener_df = get_project_screener(df, min_sales_12m=screener_min_sales)

    if screener_df.empty:
        st.warning(
            "No project-level data available for the current sidebar filters. "
            "Try broadening the district selection or reducing the Min. Transactions threshold."
        )
    else:
        # Apply inline filters
        _scr = screener_df.copy()
        if sel_screener_districts:
            _scr = _scr[_scr["district"].str.title().isin(sel_screener_districts)]
        if sel_screener_types:
            _scr = _scr[_scr["property_type"].isin(sel_screener_types)]

        # Only chart projects with enough data for both axes
        _scr_chartable = _scr[
            _scr["vs_district_pct"].notna() &
            _scr["price_momentum_pct"].notna()
        ]

        if not _scr_chartable.empty:
            st.plotly_chart(
                fig_project_screener_scatter(_scr_chartable),
                use_container_width=True,
            )
            st.caption(
                "X-axis: how much cheaper or more expensive the project is vs its district median (last 12M). "
                "Y-axis: 3-month price momentum. "
                "Bubble size = 12-month transaction volume. "
                "Top-left quadrant = discounted and rising — strongest buy signals."
            )
        else:
            st.info(
                "Not enough data to render the scatter chart for the current filters. "
                "Projects need both vs-district and 3M momentum data. "
                "Try broadening filters or reducing the Min 12M sales threshold."
            )

        # Sortable table
        _display_scr = _scr[[
            "project", "district", "property_type",
            "median_rate", "vs_district_pct", "price_momentum_pct",
            "sales_12m", "velocity_signal", "signal",
        ]].copy()
        _display_scr["district"] = _display_scr["district"].str.title()
        _display_scr["property_type"] = _display_scr["property_type"].map(
            config.PROPERTY_TYPE_LABELS
        ).fillna(_display_scr["property_type"].str.title())
        _display_scr["median_rate"] = _display_scr["median_rate"].round(0).astype("Int64")
        _display_scr["vs_district_pct"] = _display_scr["vs_district_pct"].round(1)
        _display_scr["price_momentum_pct"] = _display_scr["price_momentum_pct"].round(1)
        _display_scr["velocity_signal"] = _display_scr["velocity_signal"].round(2)
        _display_scr.columns = [
            "Project", "District", "Type",
            "Median Rate (AED/sqm)", "vs District %", "3M Momentum %",
            "12M Sales", "Velocity", "Signal",
        ]

        st.dataframe(
            _display_scr,
            use_container_width=True,
            hide_index=True,
            column_config={
                "vs District %": st.column_config.NumberColumn(
                    "vs District %",
                    format="%.1f%%",
                    help="Negative = below district median = potential discount",
                ),
                "3M Momentum %": st.column_config.NumberColumn(
                    "3M Momentum %",
                    format="%.1f%%",
                    help="Recent 3M price vs prior 3M. Positive = rising.",
                ),
                "Velocity": st.column_config.NumberColumn(
                    "Velocity",
                    format="%.2fx",
                    help="Recent quarter sales vs average quarter. >1.2 = accelerating demand.",
                ),
                "Signal": st.column_config.TextColumn(
                    "Signal",
                    help="promising = discounted + rising. value_trap = cheap but losing velocity. neutral = no strong signal. insufficient = too few transactions.",
                ),
            },
        )
        st.caption(
            f"{len(_scr):,} projects shown. "
            "Green signal = discounted vs district and price rising. "
            "Red = cheap but velocity falling (value trap). "
            "Sort any column by clicking the header."
        )

    st.divider()

    # ── Section B: Project Deep Dive ─────────────────────────────────────────
    st.subheader("Section B — Project Deep Dive")

    if screener_df.empty:
        st.info("No projects available for deep dive. Broaden your sidebar filters.")
    else:
        all_projects = sorted(screener_df["project"].dropna().unique().tolist())
        # Pre-select the top promising project if any exist
        _promising = screener_df[screener_df["signal"] == "promising"]["project"].tolist()
        _default_proj_idx = (
            all_projects.index(_promising[0])
            if _promising and _promising[0] in all_projects
            else 0
        )
        selected_project = st.selectbox(
            "Select a project to analyse",
            options=all_projects,
            index=_default_proj_idx,
            key="pi_project_select",
        )

        # Look up district + type for this project
        _proj_row = screener_df[screener_df["project"] == selected_project].iloc[0]
        _proj_district = _proj_row["district"]
        _proj_type = _proj_row["property_type"]

        # KPI tiles
        _rate = _proj_row["median_rate"]
        _vs_d = _proj_row["vs_district_pct"]
        _sales_12m = int(_proj_row["sales_12m"])
        _vel = _proj_row["velocity_signal"]

        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        with kpi_c1:
            st.metric(
                "Current Rate",
                f"AED {_rate:,.0f}/sqm" if pd.notna(_rate) else "N/A",
                help="Median transaction price per sqm in the last 12 months.",
            )
        with kpi_c2:
            _vs_delta = f"{_vs_d:+.1f}%" if pd.notna(_vs_d) else None
            st.metric(
                "vs District",
                f"{_vs_d:+.1f}%" if pd.notna(_vs_d) else "N/A",
                delta=_vs_delta,
                delta_color="inverse",
                help="Negative = below district median = potential discount. Positive = premium.",
            )
        with kpi_c3:
            st.metric(
                "12M Sales",
                f"{_sales_12m:,}",
                help="Number of recorded transactions in the last 12 months.",
            )
        with kpi_c4:
            if pd.notna(_vel):
                _vel_label = "Accelerating" if _vel >= 1.2 else ("Slowing" if _vel < 0.8 else "Normal")
                st.metric(
                    "Velocity Signal",
                    f"{_vel:.2f}x",
                    delta=_vel_label,
                    delta_color="normal" if _vel >= 1.0 else "inverse",
                    help="Recent quarter sales vs avg quarter (12M / 4). >1.2 = demand accelerating.",
                )
            else:
                st.metric("Velocity Signal", "N/A")

        # Price trend chart
        proj_monthly = get_project_monthly_rate(df, selected_project)
        district_monthly_ref = get_project_district_monthly(df, _proj_district, _proj_type)

        if not proj_monthly.empty:
            st.plotly_chart(
                fig_project_price_trend(proj_monthly, district_monthly_ref, selected_project),
                use_container_width=True,
            )
            st.caption(
                "Monthly median price/sqm for the selected project. "
                "Dashed grey line = district median for reference. "
                "Multiple coloured lines appear when the project has multiple bedroom layouts with enough data."
            )
        else:
            st.info("Not enough monthly data to render a price trend for this project.")

        # Volume trend
        proj_vol = get_project_quarterly_volume(df, selected_project)
        if not proj_vol.empty:
            st.plotly_chart(
                fig_project_volume_bar(proj_vol, selected_project),
                use_container_width=True,
            )
            st.caption("Quarterly transaction count. Rising volume alongside stable/rising prices = strengthening demand.")
        else:
            st.info("No quarterly volume data available for this project.")

        # Asking vs Actual for this project (if PF data available)
        _pf_available_t6 = False
        try:
            from pf_scraper import load_pf_history as _load_pf_hist_t6
            from pf_processor import normalise_pf_listings as _norm_pf_t6
            _pf_available_t6 = True
        except ImportError:
            pass

        if _pf_available_t6:
            _pf_hist_t6 = _load_pf_hist_t6()
            _snaps_t6 = _pf_hist_t6.get("snapshots", [])
            if len(_snaps_t6) >= 1:
                # Build per-project asking price time-series from all snapshots
                _proj_trend_rows = []
                for _snap in _snaps_t6:
                    _sdf = _norm_pf_t6(
                        _snap.get("listings", []),
                        reference_date=(
                            __import__("datetime").datetime.fromisoformat(
                                _snap.get("collected_at", "").replace("Z", "+00:00")
                            ) if _snap.get("collected_at") else None
                        ),
                    )
                    if _sdf.empty:
                        continue
                    # Filter to matching project name (community)
                    _proj_pf = _sdf[
                        _sdf["community"].str.lower().str.contains(
                            selected_project.lower()[:20], na=False, regex=False
                        )
                    ]
                    if _proj_pf.empty:
                        continue
                    _agg_snap = (
                        _proj_pf
                        .groupby(["community", "beds"])["price_per_sqm"]
                        .median()
                        .reset_index()
                        .rename(columns={"price_per_sqm": "median_asking_rate"})
                    )
                    _agg_snap["snap_date"] = _snap.get("month", "")
                    _proj_trend_rows.append(_agg_snap)

                if _proj_trend_rows:
                    _pf_proj_trend = pd.concat(_proj_trend_rows, ignore_index=True)
                    # Only show if at least 2 data points exist
                    if len(_pf_proj_trend) >= 2:
                        st.markdown("**Asking Price Trend (Property Finder snapshots)**")
                        st.plotly_chart(
                            fig_pf_project_asking_trend(_pf_proj_trend),
                            use_container_width=True,
                        )
                        st.caption(
                            "Median asking price per sqm per bedroom type, tracked across all saved "
                            "Property Finder snapshots for this project. Requires at least 2 snapshots."
                        )

    st.divider()

    # ── Section C: Asking Price Trends by Project (PF snapshots) ─────────────
    st.subheader("Section C — Asking Price Trends by Project (PF Snapshots)")

    _pf_c_available = False
    try:
        from pf_scraper import load_pf_history as _load_pf_c
        from pf_processor import normalise_pf_listings as _norm_pf_c
        _pf_c_available = True
    except ImportError:
        pass

    if not _pf_c_available:
        st.info(
            "Property Finder snapshot data is not available. "
            "Use the **Asking vs Actual** tab to collect snapshots first."
        )
    else:
        _pf_hist_c = _load_pf_c()
        _snaps_c = _pf_hist_c.get("snapshots", [])

        if len(_snaps_c) < 2:
            st.info(
                "Collect at least two Property Finder snapshots to track asking price trends by project. "
                "Use the **Asking vs Actual** tab to save snapshots."
            )
        else:
            # Build full cross-snapshot time series grouped by (community, beds, type)
            _all_snap_rows = []
            for _snap in _snaps_c:
                _ts = _snap.get("collected_at", "")
                _ref = None
                if _ts:
                    try:
                        import datetime as _dtt
                        _ref = _dtt.datetime.fromisoformat(_ts.replace("Z", "+00:00"))
                    except Exception:
                        pass
                _sdf_c = _norm_pf_c(_snap.get("listings", []), reference_date=_ref)
                if _sdf_c.empty:
                    continue
                _agg_c = (
                    _sdf_c
                    .groupby(["community", "beds", "type"])["price_per_sqm"]
                    .median()
                    .reset_index()
                    .rename(columns={"price_per_sqm": "median_asking_rate"})
                )
                _agg_c["snap_date"] = _snap.get("month", "")
                _all_snap_rows.append(_agg_c)

            if not _all_snap_rows:
                st.info("No parseable snapshot data found.")
            else:
                _full_trend = pd.concat(_all_snap_rows, ignore_index=True)
                _full_trend = _full_trend[_full_trend["community"].str.strip() != ""]

                # Filters
                c_col1, c_col2, c_col3 = st.columns([3, 2, 2])
                with c_col1:
                    _community_search = st.text_input(
                        "Search project / community name",
                        value="",
                        key="pi_community_search",
                        placeholder="Type to filter…",
                    )
                with c_col2:
                    _beds_opts = sorted(_full_trend["beds"].dropna().unique().tolist())
                    _sel_beds_c = st.multiselect(
                        "Filter by beds",
                        options=_beds_opts,
                        default=[],
                        placeholder="All",
                        key="pi_beds_filter",
                    )
                with c_col3:
                    _type_opts_c = sorted(_full_trend["type"].dropna().unique().tolist())
                    _sel_type_c = st.multiselect(
                        "Filter by type",
                        options=[t.title() for t in _type_opts_c],
                        default=[],
                        placeholder="All",
                        key="pi_type_filter_c",
                    )

                _ft = _full_trend.copy()
                if _community_search.strip():
                    _ft = _ft[_ft["community"].str.lower().str.contains(
                        _community_search.strip().lower(), na=False, regex=False
                    )]
                if _sel_beds_c:
                    _ft = _ft[_ft["beds"].isin(_sel_beds_c)]
                if _sel_type_c:
                    _ft = _ft[_ft["type"].isin([t.lower() for t in _sel_type_c])]

                # Keep only (community, beds) combos that appear in >= 2 snapshots
                _combo_counts = _ft.groupby(["community", "beds"])["snap_date"].nunique()
                _valid_combos = _combo_counts[_combo_counts >= 2].reset_index()[["community", "beds"]]
                _ft = _ft.merge(_valid_combos, on=["community", "beds"], how="inner")

                if _ft.empty:
                    st.info(
                        "No project+bedroom combinations appear in 2 or more snapshots for the current filter. "
                        "Try broadening the search or collecting more snapshots."
                    )
                else:
                    st.plotly_chart(
                        fig_pf_project_asking_trend(_ft),
                        use_container_width=True,
                    )
                    st.caption(
                        "Tracks how median asking prices per project and unit size have changed "
                        "across your saved snapshots. Only combinations with data in at least "
                        "2 snapshots are shown."
                    )
