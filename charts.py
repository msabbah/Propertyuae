import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import config
from analytics import DecompositionResult


# ─────────────────────────────────────────────
# Tab 1: Price History
# ─────────────────────────────────────────────

def fig_price_trend_line(df_monthly: pd.DataFrame, color_by: str = None) -> go.Figure:
    """Monthly median rate/SQM trend line. color_by: column name or None."""
    fig = go.Figure()

    if color_by and color_by in df_monthly.columns:
        groups = df_monthly[color_by].unique()
        color_map = (
            config.DISTRICT_COLORS if color_by == config.COL_DISTRICT
            else config.PROPERTY_TYPE_COLORS
        )
        for group in sorted(groups):
            gdf = df_monthly[df_monthly[color_by] == group].sort_values(config.COL_YEARMONTH)
            display = group.title() if isinstance(group, str) else str(group)
            color = color_map.get(group, None)
            n_col = gdf.get("transaction_count", None)
            hover = (
                f"<b>{display}</b><br>%{{x|%b %Y}}<br>AED %{{y:,.0f}}/SQM"
                + ("<br>n=%{customdata:,}<extra></extra>" if n_col is not None else "<extra></extra>")
            )
            fig.add_trace(go.Scatter(
                x=gdf[config.COL_YEARMONTH],
                y=gdf["median_rate"],
                customdata=n_col if n_col is not None else None,
                mode="lines",
                name=display,
                line=dict(color=color, width=2),
                hovertemplate=hover,
            ))
    else:
        df_s = df_monthly.sort_values(config.COL_YEARMONTH)
        n_col = df_s.get("transaction_count", None)
        hover = (
            "%{x|%b %Y}<br>AED %{y:,.0f}/SQM"
            + ("<br>n=%{customdata:,}<extra></extra>" if n_col is not None else "<extra></extra>")
        )
        fig.add_trace(go.Scatter(
            x=df_s[config.COL_YEARMONTH],
            y=df_s["median_rate"],
            customdata=n_col if n_col is not None else None,
            mode="lines",
            name="Median Rate",
            line=dict(color="#4e79a7", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(78,121,167,0.08)",
            hovertemplate=hover,
        ))

    fig.update_layout(
        title="Monthly Median Price (AED/SQM)",
        xaxis=dict(title="", rangeslider=dict(visible=True), rangeselector=dict(
            buttons=[
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=3, label="3Y", step="year", stepmode="backward"),
                dict(step="all", label="All"),
            ]
        )),
        yaxis=dict(title="AED / SQM", tickformat=",", rangemode="normal"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=450,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_yoy_overlay(
    df_yoy: pd.DataFrame,
    indexed: bool = False,
    segment_label: str = "",
) -> go.Figure:
    """Year-on-year overlay: one line per year on Jan–Dec x-axis.

    Args:
        indexed: When True, each year's values are expressed as % deviation from
                 that year's own annual median.  This removes the absolute price
                 level and exposes pure intra-year seasonal patterns.
        segment_label: Optional label appended to the chart title (e.g. district name).
    """
    import numpy as np

    fig = go.Figure()
    years = sorted(df_yoy[config.COL_YEAR].unique())
    current_year = df_yoy[config.COL_YEAR].max()

    # Color ramp: historical years fade from steel-blue to grey; current year is navy
    CURRENT_COLOR = "#1e3a5f"
    HISTORICAL_COLOR = "#9e9e9e"

    for year in years:
        ydf = df_yoy[df_yoy[config.COL_YEAR] == year].sort_values(config.COL_MONTH)
        is_current = year == current_year

        y_vals = ydf["median_rate"].values.copy()
        if indexed:
            annual_median = np.median(y_vals)
            if annual_median and annual_median > 0:
                y_vals = (y_vals - annual_median) / annual_median * 100
            else:
                y_vals = np.full_like(y_vals, np.nan, dtype=float)
            hover_suffix = "%"
            hover_fmt = ".1f"
        else:
            hover_suffix = " AED/sqm"
            hover_fmt = ",.0f"

        x_labels = ydf[config.COL_MONTH].map(lambda m: config.MONTH_NAMES[m - 1])

        if indexed:
            hover_tmpl = (
                f"<b>{year}</b><br>%{{x}}<br>%{{y:{hover_fmt}}}{hover_suffix}"
                "<extra></extra>"
            )
        else:
            hover_tmpl = (
                f"<b>{year}</b><br>%{{x}}<br>AED %{{y:{hover_fmt}}}/sqm"
                "<extra></extra>"
            )

        fig.add_trace(go.Scatter(
            x=x_labels,
            y=y_vals,
            mode="lines+markers" if is_current else "lines",
            name=str(year),
            line=dict(
                color=CURRENT_COLOR if is_current else HISTORICAL_COLOR,
                width=3 if is_current else 1,
                dash="solid",
            ),
            opacity=1.0 if is_current else 0.5,
            marker=dict(size=6, color=CURRENT_COLOR) if is_current else dict(size=0),
            hovertemplate=hover_tmpl,
        ))

    if indexed:
        title = "Seasonal Price Pattern — % vs Annual Median"
        yaxis_cfg = dict(
            title="% vs annual median",
            ticksuffix="%",
            zeroline=True,
            zerolinecolor="#c0c8d4",
            zerolinewidth=1.5,
        )
    else:
        title = "Year-on-Year Price Comparison (Jan–Dec)"
        yaxis_cfg = dict(title="AED / sqm", tickformat=",")

    if segment_label:
        title = f"{title} · {segment_label}"

    fig.update_layout(
        title=title,
        xaxis=dict(
            title="Month",
            categoryorder="array",
            categoryarray=config.MONTH_NAMES,
        ),
        yaxis=yaxis_cfg,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            title_text="Year",
        ),
        hovermode="x unified",
        height=420,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_price_heatmap(df_heatmap: pd.DataFrame) -> go.Figure:
    """District × Year heatmap with relative coloring per district."""
    pivot = df_heatmap.pivot_table(
        index=config.COL_DISTRICT, columns=config.COL_YEAR,
        values="median_rate", aggfunc="median"
    )
    # Z-score per district row for relative coloring.
    # Districts with only one year of data produce std=0 → NaN row (shown as blank).
    z = pivot.apply(lambda row: (row - row.mean()) / (row.std() if row.std() > 0 else 1), axis=1)

    fig = go.Figure(go.Heatmap(
        z=z.values,
        x=[str(c) for c in pivot.columns],
        y=pivot.index.tolist(),
        customdata=pivot.values,
        colorscale="RdYlGn",
        zmid=0,
        colorbar=dict(
            title=dict(text="vs District's<br>Own Average", side="right"),
            tickvals=[-2, -1, 0, 1, 2],
            ticktext=["−2σ Below", "−1σ", "Average", "+1σ", "+2σ Above"],
        ),
        hovertemplate=(
            "<b>%{y}</b><br>Year: %{x}<br>"
            "Actual rate: AED %{customdata:,.0f}/SQM<br>"
            "<i>Colour = vs this district's own average (not cross-district)</i>"
            "<extra></extra>"
        ),
    ))
    fig.update_layout(
        title="District Price Trend — Colour Relative to Each District's Own Historical Average",
        xaxis=dict(title="Year"),
        yaxis=dict(title="", autorange="reversed"),
        height=max(350, len(pivot) * 30 + 100),
        margin=dict(t=60, l=160, b=40),
    )
    return fig


def fig_layout_box(df_layout: pd.DataFrame, property_type: str = "apartment") -> go.Figure:
    """Horizontal box chart: price/sqm range by bedroom layout.

    Sorted cheapest → most expensive (bottom → top).
    Each layout gets a distinct shade of the property-type hue.
    Median value annotated directly on the chart.
    """
    df_s = df_layout.sort_values("median_rate").reset_index(drop=True)
    n_rows = len(df_s)

    # Build a colour ramp: lightest for cheapest layout, darkest for most expensive.
    # Base hue from property type, mapped to a 5-stop ramp.
    base_colors = {
        "apartment":                  ["#aec6e8", "#7aafd4", "#4a9edd", "#2275b5", "#0f4c81"],
        "villa":                      ["#fdd0a2", "#fdae6b", "#fd8d3c", "#e6550d", "#a63603"],
        "townhouse / attached villa": ["#b8ddb0", "#74c476", "#41ab5d", "#238b45", "#00441b"],
    }
    ramp = base_colors.get(property_type, base_colors["apartment"])
    # Interpolate ramp to n_rows colours
    import math
    def _pick_color(i, total, colors):
        if total == 1:
            return colors[len(colors) // 2]
        idx = i / max(total - 1, 1) * (len(colors) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(colors) - 1)
        frac = idx - lo
        def _hex_lerp(c1, c2, t):
            r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
            r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
            r = int(r1 + (r2-r1)*t)
            g = int(g1 + (g2-g1)*t)
            b = int(b1 + (b2-b1)*t)
            return f"#{r:02x}{g:02x}{b:02x}"
        return _hex_lerp(colors[lo], colors[hi], frac)

    fig = go.Figure()

    for i, row in df_s.iterrows():
        layout = str(row[config.COL_LAYOUT]).title()
        color = _pick_color(i, n_rows, ramp)
        fig.add_trace(go.Box(
            name=layout,
            # Horizontal: x = values, y = category
            x=[row["p10_rate"], row["p25_rate"], row["median_rate"],
               row["p75_rate"], row["p90_rate"]],
            lowerfence=[row["p10_rate"]],
            q1=[row["p25_rate"]],
            median=[row["median_rate"]],
            q3=[row["p75_rate"]],
            upperfence=[row["p90_rate"]],
            orientation="h",
            marker_color=color,
            line_color=color,
            fillcolor=color,
            opacity=0.85,
            hovertemplate=(
                f"<b>{layout}</b>  ·  n={row['count']:,}<br>"
                f"P10: AED {row['p10_rate']:,.0f}/sqm<br>"
                f"P25: AED {row['p25_rate']:,.0f}/sqm<br>"
                f"<b>Median: AED {row['median_rate']:,.0f}/sqm</b><br>"
                f"P75: AED {row['p75_rate']:,.0f}/sqm<br>"
                f"P90: AED {row['p90_rate']:,.0f}/sqm"
                "<extra></extra>"
            ),
        ))
        # Annotate median value directly on the chart
        fig.add_annotation(
            x=row["median_rate"],
            y=layout,
            text=f"  AED {row['median_rate']:,.0f}",
            showarrow=False,
            xanchor="left",
            font=dict(size=11, color="#1a1a2e", family="sans-serif"),
        )

    row_height = 62
    chart_height = max(300, n_rows * row_height + 80)

    fig.update_layout(
        title=dict(
            text="Price per SQM by Unit Size — Median with P10–P25–P75–P90 Range",
            font=dict(size=13),
        ),
        xaxis=dict(
            title="AED / SQM",
            tickformat=",",
            gridcolor="#e8ecf0",
            showgrid=True,
            zeroline=False,
        ),
        yaxis=dict(
            title="",
            categoryorder="array",
            categoryarray=df_s[config.COL_LAYOUT].str.title().tolist(),
            gridcolor="#e8ecf0",
        ),
        height=chart_height,
        margin=dict(t=55, b=40, l=90, r=120),
        showlegend=False,
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    return fig


def fig_price_distribution(df: pd.DataFrame, group_by: str = None) -> go.Figure:
    """KDE density curves for price/sqm, one curve per group value.

    Takes the raw (already-filtered) DataFrame so sidebar filters apply automatically.
    group_by: column to split on — defaults to COL_LAYOUT.
    """
    from scipy.stats import gaussian_kde

    group_by = group_by or config.COL_LAYOUT

    df = df.dropna(subset=[config.COL_RATE])
    df = df[df[config.COL_RATE] > 0]

    if df.empty:
        return go.Figure()

    # Layout order mirrors natural bedroom progression
    LAYOUT_ORDER = ["studio", "1 bed", "2 beds", "3 beds", "4 beds", "5+ beds", "6+ beds"]
    LAYOUT_COLORS = {
        "studio":   "#8e44ad",
        "1 bed":    "#2980b9",
        "2 beds":   "#27ae60",
        "3 beds":   "#e67e22",
        "4 beds":   "#e74c3c",
        "5+ beds":  "#16a085",
        "6+ beds":  "#2c3e50",
    }
    FALLBACK = ["#3498db","#e74c3c","#2ecc71","#f39c12","#9b59b6","#1abc9c","#e67e22","#34495e"]

    def _hex_rgb(h):
        h = h.lstrip("#")
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"

    all_rates = df[config.COL_RATE].values
    x_min = max(float(np.percentile(all_rates, 0.5)), 0)
    x_max = float(np.percentile(all_rates, 99.5))
    x_vals = np.linspace(x_min, x_max, 500)

    # Determine group order
    raw_groups = df[group_by].dropna().unique().tolist()
    if group_by == config.COL_LAYOUT:
        groups = [g for g in LAYOUT_ORDER if g in raw_groups]
        groups += [g for g in raw_groups if g not in groups]
    else:
        groups = sorted(raw_groups)

    fig = go.Figure()
    fallback_idx = 0

    for grp in groups:
        rates = df[df[group_by] == grp][config.COL_RATE].dropna().values
        if len(rates) < 15:
            continue

        label = str(grp).title()
        color = LAYOUT_COLORS.get(str(grp).lower())
        if color is None:
            color = FALLBACK[fallback_idx % len(FALLBACK)]
            fallback_idx += 1

        try:
            kde = gaussian_kde(rates, bw_method="scott")
            y_vals = kde(x_vals)
        except Exception:
            continue

        median_val = float(np.median(rates))
        p25 = float(np.percentile(rates, 25))
        p75 = float(np.percentile(rates, 75))

        # Filled area under curve
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines",
            name=f"{label} (n={len(rates):,})",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({_hex_rgb(color)},0.10)",
            hovertemplate=(
                f"<b>{label}</b><br>"
                "AED %{x:,.0f}/sqm<br>"
                "<extra></extra>"
            ),
        ))

        # Median marker as a vertical annotation
        med_density = float(kde(np.array([median_val]))[0])
        fig.add_shape(
            type="line",
            x0=median_val, x1=median_val,
            y0=0, y1=med_density,
            line=dict(color=color, width=1.5, dash="dot"),
        )
        fig.add_annotation(
            x=median_val,
            y=med_density,
            text=f"<b>{label}</b><br>AED {median_val:,.0f}",
            showarrow=False,
            yshift=8,
            font=dict(size=9, color=color),
            bgcolor="rgba(255,255,255,0.75)",
            borderpad=2,
        )

    group_label = {
        config.COL_LAYOUT:        "Bedroom Layout",
        config.COL_PROPERTY_TYPE: "Property Type",
        config.COL_DISTRICT:      "District",
    }.get(group_by, group_by)

    fig.update_layout(
        title=f"Price / sqm Distribution by {group_label}",
        xaxis=dict(
            title="AED / sqm",
            tickformat=",",
            range=[x_min, x_max],
            gridcolor="#eaeef2",
        ),
        yaxis=dict(
            title="Relative density",
            showticklabels=False,
            gridcolor="#eaeef2",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        hovermode="x unified",
        height=440,
        margin=dict(t=60, b=40, l=40, r=20),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    return fig


# ─────────────────────────────────────────────
# Tab 2: Market Activity
# ─────────────────────────────────────────────

def fig_volume_bar(df_volume: pd.DataFrame, group_by: str = None) -> go.Figure:
    """Quarterly transaction volume, optionally stacked by a group column."""
    fig = go.Figure()

    if group_by and group_by in df_volume.columns:
        groups = df_volume[group_by].unique()
        color_map = (
            config.DISTRICT_COLORS if group_by == config.COL_DISTRICT
            else config.PROPERTY_TYPE_COLORS
        )
        for group in sorted(groups):
            gdf = df_volume[df_volume[group_by] == group]
            display = str(group).title()
            fig.add_trace(go.Bar(
                x=gdf[config.COL_QUARTER],
                y=gdf["transaction_count"],
                name=display,
                marker_color=color_map.get(group, None),
                hovertemplate=f"<b>{display}</b><br>%{{x}}<br>%{{y:,}} transactions<extra></extra>",
            ))
        fig.update_layout(barmode="stack")
    else:
        fig.add_trace(go.Bar(
            x=df_volume[config.COL_QUARTER],
            y=df_volume["transaction_count"],
            marker_color="#4e79a7",
            hovertemplate="%{x}<br>%{y:,} transactions<extra></extra>",
            showlegend=False,
        ))

    fig.update_layout(
        title="Quarterly Transaction Volume",
        xaxis=dict(title="Quarter"),
        yaxis=dict(title="Transactions", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_off_plan_vs_ready(df_sale_type: pd.DataFrame) -> go.Figure:
    """Monthly area chart: off-plan vs ready transaction volume."""
    fig = go.Figure()
    for sale_type in ["ready", "off-plan"]:
        sdf = df_sale_type[df_sale_type[config.COL_SALE_TYPE] == sale_type]
        fig.add_trace(go.Scatter(
            x=sdf[config.COL_YEARMONTH],
            y=sdf["count"],
            name=sale_type.title(),
            mode="lines",
            stackgroup="one",
            fillcolor=config.SALE_TYPE_COLORS.get(sale_type, None),
            line=dict(color=config.SALE_TYPE_COLORS.get(sale_type, None), width=0.5),
            hovertemplate=f"<b>{sale_type.title()}</b><br>%{{x|%b %Y}}<br>%{{y:,}} transactions<extra></extra>",
        ))
    fig.update_layout(
        title="Monthly Transactions: Off-Plan vs Ready",
        xaxis=dict(title=""),
        yaxis=dict(title="Transactions", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=380,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_market_share_pie(df_share: pd.DataFrame) -> go.Figure:
    """Donut chart: transaction share by district, colour-coded by district."""
    # Extended palette for districts not in config.DISTRICT_COLORS
    _EXTRA_COLORS = [
        "#3498db", "#e67e22", "#2ecc71", "#9b59b6", "#e74c3c",
        "#1abc9c", "#f39c12", "#2980b9", "#8e44ad", "#27ae60",
        "#d35400", "#c0392b", "#16a085", "#7f8c8d", "#2c3e50",
    ]
    _extra_idx = [0]

    def _color(district: str) -> str:
        # Keys in DISTRICT_COLORS are lowercase
        c = config.DISTRICT_COLORS.get(district.lower(), None)
        if c:
            return c
        # Assign a deterministic colour from the extended palette for unknown districts
        c = _EXTRA_COLORS[_extra_idx[0] % len(_EXTRA_COLORS)]
        _extra_idx[0] += 1
        return c

    colors = [_color(d) for d in df_share["district"]]
    labels = [d.title() if d != "Other" else d for d in df_share["district"]]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=df_share["count"],
        hole=0.45,
        marker=dict(
            colors=colors,
            line=dict(color="#ffffff", width=1.5),
        ),
        textinfo="label+percent",
        textfont=dict(size=11),
        hovertemplate="<b>%{label}</b><br>%{value:,} transactions (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title="Transaction Share by District",
        height=420,
        margin=dict(t=60, b=20),
        showlegend=True,
        legend=dict(orientation="v", x=1.02, y=0.5, xanchor="left"),
    )
    return fig


def fig_price_band_histogram(df_bands: pd.DataFrame) -> go.Figure:
    """Grouped bar: transaction count by price band and property type."""
    band_order = [b[2] for b in config.PRICE_BANDS]
    fig = go.Figure()
    for ptype in df_bands["property_type"].unique():
        pdf = df_bands[df_bands["property_type"] == ptype]
        display = config.PROPERTY_TYPE_LABELS.get(ptype, ptype.title())
        fig.add_trace(go.Bar(
            name=display,
            x=pdf["price_band"],
            y=pdf["count"],
            marker_color=config.PROPERTY_TYPE_COLORS.get(ptype, None),
            hovertemplate=f"<b>{display}</b><br>%{{x}}<br>%{{y:,}} transactions<extra></extra>",
        ))
    fig.update_layout(
        title="Price Band Distribution by Property Type",
        xaxis=dict(title="Price Range (AED)", categoryorder="array", categoryarray=band_order),
        yaxis=dict(title="Transactions", tickformat=","),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380,
        margin=dict(t=60, b=40),
    )
    return fig


# ─────────────────────────────────────────────
# Tab 3: Best Time to Enter
# ─────────────────────────────────────────────

def fig_seasonality_wheel(df_signals: pd.DataFrame) -> go.Figure:
    """Polar bar chart: 12 months, bar length = entry score (longer = better entry).

    Entry score = 100 - composite_signal, so Tier 1 (best) shows the longest bar,
    matching the universal polar chart convention (bigger = better).
    """
    tier_color_map = {
        1: config.TIER_COLORS[1],
        2: config.TIER_COLORS[2],
        3: config.TIER_COLORS[3],
        4: config.TIER_COLORS[4],
    }
    colors = [tier_color_map[t] for t in df_signals["tier"]]
    entry_score = 100 - df_signals["composite_signal"]

    fig = go.Figure(go.Barpolar(
        r=entry_score,
        theta=df_signals["month_name"],
        width=[30] * 12,
        marker=dict(
            color=colors,
            line=dict(color="white", width=1),
        ),
        hovertemplate=(
            "<b>%{theta}</b><br>"
            "Entry Score: %{r:.1f} / 100<br>"
            "Higher = better time to buy<extra></extra>"
        ),
    ))
    # Add invisible scatter traces to force a proper colour legend for the 4 tiers
    for tier_num, tier_label in config.TIER_LABELS.items():
        fig.add_trace(go.Scatterpolar(
            r=[None],
            theta=[None],
            mode="markers",
            name=tier_label,
            marker=dict(color=config.TIER_COLORS[tier_num], size=10, symbol="square"),
            showlegend=True,
        ))

    fig.update_layout(
        title="Seasonal Entry Score (Higher = Better Time to Buy)",
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=True),
            angularaxis=dict(direction="clockwise", rotation=90),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
            title_text="Entry Tier",
        ),
        height=520,
        margin=dict(t=80, b=60),
        showlegend=True,
    )
    return fig


def fig_entry_signal_bars(df_signals: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart: months ranked by entry score (longer bar = better month).

    Entry score = 100 - composite_signal so best months have the highest/longest bars,
    consistent with the polar wheel direction.
    """
    df_s = df_signals.copy()
    df_s["entry_score"] = 100 - df_s["composite_signal"]
    df_s = df_s.sort_values("entry_score", ascending=True)  # best at top
    tier_color_map = {t: config.TIER_COLORS[t] for t in [1, 2, 3, 4]}
    colors = [tier_color_map[t] for t in df_s["tier"]]

    fig = go.Figure(go.Bar(
        x=df_s["entry_score"],
        y=df_s["month_name"],
        orientation="h",
        marker_color=colors,
        text=[f"  {row['tier_label']}" for _, row in df_s.iterrows()],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Entry Score: %{x:.1f} / 100 (higher = better)<extra></extra>",
    ))
    fig.update_layout(
        title="Monthly Entry Score — Best to Worst (Higher = Better Time to Buy)",
        xaxis=dict(title="Entry Score (0–100)", range=[0, 115]),
        yaxis=dict(title=""),
        height=420,
        margin=dict(t=60, l=60, r=80, b=40),
        showlegend=False,
    )
    return fig


def fig_seasonal_component(df_signals: pd.DataFrame) -> go.Figure:
    """Line chart: seasonal adjustment in AED/SQM by month."""
    fig = go.Figure(go.Scatter(
        x=df_signals["month_name"],
        y=df_signals["seasonal_adjustment_aed"],
        mode="lines+markers",
        line=dict(color="#4e79a7", width=2.5),
        marker=dict(size=8),
        fill="tozeroy",
        fillcolor="rgba(78,121,167,0.1)",
        hovertemplate="<b>%{x}</b><br>Seasonal adjustment: AED %{y:+,.0f}/SQM<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title="Seasonal Price Adjustment by Month (AED/SQM vs Trend)",
        xaxis=dict(title="Month", categoryorder="array", categoryarray=config.MONTH_NAMES),
        yaxis=dict(title="Seasonal Adjustment (AED/SQM)", tickformat="+,"),
        height=360,
        margin=dict(t=60, b=40),
    )
    return fig


# ─────────────────────────────────────────────
# Tab 4: Trend & Forecast
# ─────────────────────────────────────────────

def fig_decomposition_panel(decomp: DecompositionResult) -> go.Figure:
    """4-panel decomposition: Observed / Trend / Seasonal / Residual."""
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        subplot_titles=["Observed (Raw Data)", "Trend (Noise Removed)", "Seasonal Component (Annual Cycle)", "Residual (Unexplained Variation)"],
        vertical_spacing=0.07,
    )
    panel_data = [
        (decomp.observed, "#4e79a7", 1, "AED/SQM"),
        (decomp.trend, "#f28e2b", 2, "AED/SQM"),
        (decomp.seasonal, "#59a14f", 3, "Adjustment (AED/SQM)"),
        (decomp.residual, "#e15759", 4, "Residual (AED/SQM)"),
    ]
    for series, color, row, ylabel in panel_data:
        fig.add_trace(go.Scatter(
            x=series.index,
            y=series.values,
            mode="lines",
            line=dict(color=color, width=1.8),
            showlegend=False,
            hovertemplate="%{x|%b %Y}<br>%{y:,.0f}<extra></extra>",
        ), row=row, col=1)
        fig.update_yaxes(title_text=ylabel, tickformat=",", row=row, col=1)

    fig.update_layout(
        height=560,
        margin=dict(t=40, b=40),
        hovermode="x unified",
    )
    return fig


def fig_trend_projection(historical: pd.DataFrame, projection: pd.DataFrame) -> go.Figure:
    """Historical trend + projected values with CI band."""
    fig = go.Figure()

    # Historical trend
    fig.add_trace(go.Scatter(
        x=historical["date"],
        y=historical["trend_value"],
        mode="lines",
        name="Historical",
        line=dict(color="#4e79a7", width=2),
        hovertemplate="%{x|%b %Y}<br>AED %{y:,.0f}/SQM<extra></extra>",
    ))

    # CI band
    fig.add_trace(go.Scatter(
        x=pd.concat([projection["date"], projection["date"].iloc[::-1]]),
        y=pd.concat([projection["ci_upper"], projection["ci_lower"].iloc[::-1]]),
        fill="toself",
        fillcolor="rgba(242,142,43,0.2)",
        line=dict(color="rgba(255,255,255,0)"),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Projected line
    fig.add_trace(go.Scatter(
        x=projection["date"],
        y=projection["projected_value"],
        mode="lines",
        name="Projection",
        line=dict(color="#f28e2b", width=2.5, dash="dash"),
        hovertemplate="%{x|%b %Y}<br>Projected: AED %{y:,.0f}/SQM<extra></extra>",
    ))

    # Today marker (manual shape to avoid Plotly timestamp annotation bug)
    today_str = historical["date"].max().strftime("%Y-%m-%d")
    fig.add_shape(
        type="line", x0=today_str, x1=today_str, y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(dash="dot", color="gray", width=1),
    )
    fig.add_annotation(
        x=today_str, y=1, xref="x", yref="paper",
        text="Latest data", showarrow=False,
        xanchor="left", yanchor="top",
        font=dict(size=11, color="gray"),
    )

    fig.update_layout(
        title="Price Trend & 6-Month Projection (95% CI)",
        xaxis=dict(title=""),
        yaxis=dict(title="AED / SQM", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_momentum_gauge_dual(mom_3m: float, mom_12m: float) -> go.Figure:
    """Side-by-side gauges: 3-month (short-term) and 12-month (trend confirmation) momentum."""
    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "indicator"}, {"type": "indicator"}]],
        subplot_titles=["3-Month Momentum", "12-Month Momentum"],
    )

    for col, (val, label) in enumerate([(mom_3m, "3M"), (mom_12m, "12M")], start=1):
        color = "#1a9641" if val > 0 else "#d7191c"
        abs_val = abs(val) if val == val else 0
        scale = max(15.0, abs_val * 1.25)
        scale = round(scale / 5) * 5
        fig.add_trace(go.Indicator(
            mode="gauge+number+delta",
            value=val,
            number=dict(suffix="%", valueformat=".1f"),
            gauge=dict(
                axis=dict(range=[-scale, scale], tickformat=".0f", ticksuffix="%"),
                bar=dict(color=color),
                steps=[
                    dict(range=[-scale, -scale / 3], color="#fde8e8"),
                    dict(range=[-scale / 3, scale / 3], color="#fef9e7"),
                    dict(range=[scale / 3, scale], color="#e8f8ee"),
                ],
                threshold=dict(line=dict(color="black", width=2), thickness=0.75, value=0),
            ),
            delta=dict(reference=0, valueformat=".1f", suffix="%"),
        ), row=1, col=col)

    fig.update_layout(height=280, margin=dict(t=50, b=20, l=20, r=20))
    return fig


# ─────────────────────────────────────────────
# Tab 6: Project Intelligence
# ─────────────────────────────────────────────

def fig_project_screener_scatter(df: pd.DataFrame) -> go.Figure:
    """
    Scatter chart: X = vs_district_pct, Y = price_momentum_pct.
    Bubble size = sales_12m. Colour by signal tier.
    Quadrant annotations explain each region.
    """
    color_map = {
        "promising":   "#27ae60",
        "neutral":     "#f39c12",
        "value_trap":  "#e74c3c",
        "insufficient": "#aaaaaa",
    }
    label_map = {
        "promising":   "Promising",
        "neutral":     "Neutral",
        "value_trap":  "Value Trap",
        "insufficient": "Insufficient Data",
    }

    fig = go.Figure()

    for signal in ["promising", "neutral", "value_trap", "insufficient"]:
        sub = df[df["signal"] == signal]
        if sub.empty:
            continue
        # Bubble sizes: scale sales_12m to a visible range 6–40
        max_sales = df["sales_12m"].max() if df["sales_12m"].max() > 0 else 1
        sizes = (sub["sales_12m"] / max_sales * 34 + 6).clip(lower=6, upper=40)

        hover_text = (
            sub["project"] + "<br>"
            + sub["district"].str.title() + " · " + sub["property_type"].str.title() + "<br>"
            + "vs District: " + sub["vs_district_pct"].apply(lambda v: f"{v:+.1f}%" if pd.notna(v) else "n/a") + "<br>"
            + "3M Momentum: " + sub["price_momentum_pct"].apply(lambda v: f"{v:+.1f}%" if pd.notna(v) else "n/a") + "<br>"
            + "12M Sales: " + sub["sales_12m"].astype(str) + "<br>"
            + "Velocity: " + sub["velocity_signal"].apply(lambda v: f"{v:.2f}x" if pd.notna(v) else "n/a")
        )

        fig.add_trace(go.Scatter(
            x=sub["vs_district_pct"],
            y=sub["price_momentum_pct"],
            mode="markers",
            name=label_map[signal],
            marker=dict(
                color=color_map[signal],
                size=sizes,
                opacity=0.75,
                line=dict(width=0.5, color="white"),
            ),
            text=hover_text,
            hovertemplate="%{text}<extra></extra>",
        ))

    # Zero-axis reference lines
    fig.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
    fig.add_vline(x=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
    fig.add_vline(x=-5, line_dash="dash", line_color="#27ae60", line_width=0.7, opacity=0.4)

    # Quadrant annotations
    annotation_defaults = dict(
        showarrow=False, font=dict(size=10, color="#888888"),
        xref="paper", yref="paper",
    )
    fig.add_annotation(x=0.02, y=0.98, xanchor="left", yanchor="top",
                       text="Undervalued + Rising<br><b>Best opportunities</b>",
                       **annotation_defaults)
    fig.add_annotation(x=0.98, y=0.98, xanchor="right", yanchor="top",
                       text="Overpriced + Rising<br><b>Momentum plays</b>",
                       **annotation_defaults)
    fig.add_annotation(x=0.02, y=0.02, xanchor="left", yanchor="bottom",
                       text="Cheap + Declining<br><b>Caution / value traps</b>",
                       **annotation_defaults)
    fig.add_annotation(x=0.98, y=0.02, xanchor="right", yanchor="bottom",
                       text="Expensive + Declining<br><b>Avoid</b>",
                       **annotation_defaults)

    fig.update_layout(
        title="Project Screener: Discount vs Momentum  (bubble size = 12M transaction volume)",
        xaxis=dict(title="vs District Median (%)  — negative = below district = potential discount", ticksuffix="%", zeroline=False),
        yaxis=dict(title="3-Month Price Momentum (%)", ticksuffix="%", zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=550,
        margin=dict(t=70, b=50),
        hovermode="closest",
    )
    return fig


def fig_project_price_trend(
    project_monthly: pd.DataFrame,
    district_monthly: pd.DataFrame,
    project_name: str,
) -> go.Figure:
    """
    Line chart: monthly median rate for a project (one line per layout if multiple),
    with the district median overlaid as a dashed reference line.
    """
    fig = go.Figure()

    # District reference line
    if not district_monthly.empty:
        fig.add_trace(go.Scatter(
            x=district_monthly[config.COL_YEARMONTH],
            y=district_monthly["district_median"],
            mode="lines",
            name="District Median",
            line=dict(color="#aaaaaa", width=1.5, dash="dash"),
            hovertemplate="%{x|%b %Y}<br>District median: AED %{y:,.0f}/SQM<extra></extra>",
        ))

    # Project lines — one per layout if available
    layout_col = config.COL_LAYOUT if config.COL_LAYOUT in project_monthly.columns else None

    LAYOUT_COLORS = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#17becf",
    ]

    if layout_col and project_monthly[layout_col].nunique() > 1:
        for i, (layout, grp) in enumerate(project_monthly.groupby(layout_col)):
            grp = grp.sort_values(config.COL_YEARMONTH)
            display = str(layout).title()
            color = LAYOUT_COLORS[i % len(LAYOUT_COLORS)]
            fig.add_trace(go.Scatter(
                x=grp[config.COL_YEARMONTH],
                y=grp["median_rate"],
                mode="lines+markers",
                name=display,
                line=dict(color=color, width=2),
                marker=dict(size=5),
                hovertemplate=f"<b>{display}</b><br>%{{x|%b %Y}}<br>AED %{{y:,.0f}}/SQM<extra></extra>",
            ))
    else:
        proj_sorted = project_monthly.sort_values(config.COL_YEARMONTH)
        fig.add_trace(go.Scatter(
            x=proj_sorted[config.COL_YEARMONTH],
            y=proj_sorted["median_rate"],
            mode="lines+markers",
            name=project_name,
            line=dict(color="#4e79a7", width=2.5),
            marker=dict(size=5),
            hovertemplate="%{x|%b %Y}<br>AED %{y:,.0f}/SQM<extra></extra>",
        ))

    fig.update_layout(
        title=f"Price Trend — {project_name}",
        xaxis=dict(title=""),
        yaxis=dict(title="AED / SQM", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=400,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_project_volume_bar(df_volume: pd.DataFrame, project_name: str) -> go.Figure:
    """Quarterly transaction volume for a single project."""
    fig = go.Figure(go.Bar(
        x=df_volume[config.COL_QUARTER],
        y=df_volume["transaction_count"],
        marker_color="#4e79a7",
        hovertemplate="%{x}<br>%{y:,} transactions<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        title=f"Quarterly Sales Volume — {project_name}",
        xaxis=dict(title="Quarter"),
        yaxis=dict(title="Transactions", tickformat=","),
        height=300,
        margin=dict(t=55, b=40),
    )
    return fig


def fig_pf_project_asking_trend(trend_df: pd.DataFrame) -> go.Figure:
    """
    Time-series of median asking price/sqm per (project, beds) across PF snapshots.
    trend_df columns: snap_date, community, beds, median_asking_rate
    """
    fig = go.Figure()

    LAYOUT_COLORS = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#17becf",
        "#bcbd22", "#7f7f7f",
    ]

    groups = list(trend_df.groupby(["community", "beds"]))
    for i, ((community, beds), grp) in enumerate(groups):
        grp = grp.sort_values("snap_date")
        label = f"{community} · {beds}"
        color = LAYOUT_COLORS[i % len(LAYOUT_COLORS)]
        fig.add_trace(go.Scatter(
            x=grp["snap_date"],
            y=grp["median_asking_rate"],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2),
            marker=dict(size=6),
            hovertemplate=f"<b>{label}</b><br>%{{x}}<br>AED %{{y:,.0f}}/SQM<extra></extra>",
        ))

    fig.update_layout(
        title="Asking Price Trend by Project and Layout (across all snapshots)",
        xaxis=dict(title="Snapshot Date"),
        yaxis=dict(title="Median Asking Rate (AED/SQM)", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="center", x=0.5),
        hovermode="x unified",
        height=450,
        margin=dict(t=60, b=160),
    )
    return fig


def fig_momentum_gauge(momentum_value: float) -> go.Figure:
    """Gauge showing 3-month price momentum (%).

    Range scales dynamically so the needle never pegs at the edge of the scale.
    """
    color = "#2ecc71" if momentum_value > 0 else "#e74c3c"
    abs_val = abs(momentum_value) if momentum_value == momentum_value else 0
    scale = max(15.0, abs_val * 1.25)  # at least ±15%, always gives needle headroom
    scale = round(scale / 5) * 5       # round to nearest 5 for clean tick marks

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=momentum_value,
        number=dict(suffix="%", valueformat=".1f"),
        title=dict(text="3-Month Price Momentum", font=dict(size=16)),
        gauge=dict(
            axis=dict(range=[-scale, scale], tickformat=".0f", ticksuffix="%"),
            bar=dict(color=color),
            steps=[
                dict(range=[-scale, -scale / 3], color="#fadbd8"),
                dict(range=[-scale / 3, scale / 3], color="#fef9e7"),
                dict(range=[scale / 3, scale], color="#d5f5e3"),
            ],
            threshold=dict(line=dict(color="black", width=2), thickness=0.75, value=0),
        ),
        delta=dict(reference=0, valueformat=".1f", suffix="%"),
    ))
    fig.update_layout(height=280, margin=dict(t=40, b=20, l=20, r=20))
    return fig


# ─────────────────────────────────────────────
# Asking Price Analysis
# ─────────────────────────────────────────────

def fig_asking_trend_line(trend_df: pd.DataFrame, segment_col: str = "segment") -> go.Figure:
    """Multi-line chart of median asking rate per segment over snapshot dates.

    trend_df must contain: snap_date, median_asking_rate, pct_change_pop,
    n_listings, and a segment_col for grouping.
    """
    fig = go.Figure()

    if trend_df.empty:
        return fig

    segments = trend_df[segment_col].unique()
    colors = px.colors.qualitative.Set2
    for i, seg in enumerate(sorted(segments)):
        grp = trend_df[trend_df[segment_col] == seg].sort_values("snap_date")
        # Build hover text with % change
        hover_text = []
        for _, row in grp.iterrows():
            pop = row.get("pct_change_pop")
            pop_str = f"{pop:+.1f}%" if pd.notna(pop) else "—"
            hover_text.append(
                f"<b>{seg}</b><br>"
                f"Date: {row['snap_date']}<br>"
                f"Median: AED {row['median_asking_rate']:,.0f}/sqm<br>"
                f"MoM: {pop_str}<br>"
                f"Listings: {row['n_listings']:,}<extra></extra>"
            )
        fig.add_trace(go.Scatter(
            x=grp["snap_date"],
            y=grp["median_asking_rate"],
            mode="lines+markers",
            name=seg,
            line=dict(color=colors[i % len(colors)], width=2),
            marker=dict(size=8),
            hovertemplate="%{text}",
            text=hover_text,
        ))

    fig.update_layout(
        title="Asking Price Trend (AED/SQM)",
        xaxis=dict(title="Snapshot Date"),
        yaxis=dict(title="Median Asking Price (AED/SQM)", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="left", x=0),
        hovermode="x unified",
        height=450,
        margin=dict(t=60, b=140),
    )
    return fig


def fig_asking_vs_actual_trend(
    overlay_df: pd.DataFrame,
    segment_label: str = "",
) -> go.Figure:
    """Overlay chart: asking snapshots (scatter+line) vs actual monthly median (line).

    overlay_df must contain: snap_date, median_asking_rate, median_actual_rate, premium_pct.
    """
    fig = go.Figure()

    if overlay_df.empty:
        return fig

    df = overlay_df.sort_values("snap_date")

    # Actual transaction line (where available)
    actual_mask = df["median_actual_rate"].notna()
    if actual_mask.any():
        actual = df[actual_mask]
        fig.add_trace(go.Scatter(
            x=actual["snap_date"],
            y=actual["median_actual_rate"],
            mode="lines",
            name="Actual (Transactions)",
            line=dict(color="#16a085", width=2.5),
            hovertemplate=(
                "<b>Actual</b><br>%{x}<br>"
                "AED %{y:,.0f}/sqm<extra></extra>"
            ),
        ))

    # Asking price scatter + line
    fig.add_trace(go.Scatter(
        x=df["snap_date"],
        y=df["median_asking_rate"],
        mode="lines+markers",
        name="Asking (Property Finder)",
        line=dict(color="#8e44ad", width=2.5),
        marker=dict(size=9, symbol="diamond"),
        hovertemplate=(
            "<b>Asking</b><br>%{x}<br>"
            "AED %{y:,.0f}/sqm<extra></extra>"
        ),
    ))

    # Shaded gap between asking and actual
    if actual_mask.any():
        both = df[actual_mask].copy()
        fig.add_trace(go.Scatter(
            x=pd.concat([both["snap_date"], both["snap_date"][::-1]]),
            y=pd.concat([both["median_asking_rate"], both["median_actual_rate"][::-1]]),
            fill="toself",
            fillcolor="rgba(142, 68, 173, 0.1)",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ))

    title = "Asking vs Actual Transaction Prices"
    if segment_label:
        title += f" — {segment_label}"

    fig.update_layout(
        title=title,
        xaxis=dict(title="Date"),
        yaxis=dict(title="Median Price (AED/SQM)", tickformat=","),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=450,
        margin=dict(t=60, b=40),
    )
    return fig


def fig_asking_pct_change_bar(trend_df: pd.DataFrame, segment_col: str = "segment") -> go.Figure:
    """Bar chart of period-over-period % change per segment per snapshot.

    Green = price drop (good for buyers), Red = price rise.
    """
    fig = go.Figure()

    if trend_df.empty:
        return fig

    segments = trend_df[segment_col].unique()
    colors_palette = px.colors.qualitative.Set2

    for i, seg in enumerate(sorted(segments)):
        grp = trend_df[trend_df[segment_col] == seg].sort_values("snap_date")
        grp = grp.dropna(subset=["pct_change_pop"])
        if grp.empty:
            continue
        bar_colors = [
            "#1a9641" if v <= 0 else "#d7191c" for v in grp["pct_change_pop"]
        ]
        fig.add_trace(go.Bar(
            x=grp["snap_date"],
            y=grp["pct_change_pop"],
            name=seg,
            marker_color=bar_colors,
            hovertemplate=(
                f"<b>{seg}</b><br>"
                "%{x}<br>"
                "Change: %{y:+.1f}%<extra></extra>"
            ),
        ))

    fig.update_layout(
        title="Period-over-Period Asking Price Change (%)",
        xaxis=dict(title="Snapshot Date"),
        yaxis=dict(title="% Change", tickformat="+.1f", ticksuffix="%", zeroline=True,
                   zerolinecolor="black", zerolinewidth=1),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="left", x=0),
        barmode="group",
        height=400,
        margin=dict(t=60, b=140),
    )
    return fig


def fig_asking_cumulative_line(trend_df: pd.DataFrame, segment_col: str = "segment") -> go.Figure:
    """Indexed line chart showing cumulative % change from first snapshot (base = 0%)."""
    fig = go.Figure()

    if trend_df.empty:
        return fig

    # Zero reference line
    fig.add_hline(y=0, line_dash="dash", line_color="grey", line_width=1)

    segments = trend_df[segment_col].unique()
    colors = px.colors.qualitative.Set2

    for i, seg in enumerate(sorted(segments)):
        grp = trend_df[trend_df[segment_col] == seg].sort_values("snap_date")
        grp = grp.dropna(subset=["pct_change_cumulative"])
        if grp.empty:
            continue
        fig.add_trace(go.Scatter(
            x=grp["snap_date"],
            y=grp["pct_change_cumulative"],
            mode="lines+markers",
            name=seg,
            line=dict(color=colors[i % len(colors)], width=2),
            marker=dict(size=7),
            hovertemplate=(
                f"<b>{seg}</b><br>"
                "%{x}<br>"
                "Cumulative: %{y:+.1f}%<extra></extra>"
            ),
        ))

    fig.update_layout(
        title="Cumulative Asking Price Change (%) from First Snapshot",
        xaxis=dict(title="Snapshot Date"),
        yaxis=dict(title="Cumulative Change (%)", tickformat="+.1f", ticksuffix="%",
                   zeroline=True, zerolinecolor="black", zerolinewidth=1),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="left", x=0),
        hovermode="x unified",
        height=400,
        margin=dict(t=60, b=140),
    )
    return fig
