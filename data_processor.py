import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime
import config


def _last_complete_month_end(df: pd.DataFrame) -> pd.Timestamp:
    """Return the last day of the most recent *complete* calendar month in df.

    A complete month is any month that is not the current calendar month.
    This prevents a partial current month from distorting medians and KPIs.
    Falls back to the true last date if all data is within the current month.
    """
    current_period = pd.Period(datetime.now(), freq="M")
    complete = df[df[config.COL_DATE].dt.to_period("M") < current_period]
    if complete.empty:
        return df[config.COL_DATE].max()
    return complete[config.COL_DATE].max()


def _exclude_partial_month(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows belonging to the current (potentially incomplete) calendar month."""
    current_period = pd.Period(datetime.now(), freq="M")
    return df[df[config.COL_DATE].dt.to_period("M") < current_period]


def filter_data(
    df: pd.DataFrame,
    districts: list = None,
    property_types: list = None,
    sale_types: list = None,
    layouts: list = None,
    year_range: tuple = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)

    if districts:
        districts_lower = [d.lower() for d in districts]
        mask &= df[config.COL_DISTRICT].isin(districts_lower)

    if property_types:
        mask &= df[config.COL_PROPERTY_TYPE].isin(property_types)

    if sale_types:
        mask &= df[config.COL_SALE_TYPE].isin(sale_types)

    if layouts:
        mask &= df[config.COL_LAYOUT].isin(layouts)

    if year_range:
        mask &= (df[config.COL_YEAR] >= year_range[0]) & (df[config.COL_YEAR] <= year_range[1])

    return df[mask].copy()


@st.cache_data(max_entries=50)
def get_monthly_median_rate(
    df: pd.DataFrame,
    group_by: str = None,
    min_transactions: int = config.DEFAULT_MIN_TRANSACTIONS,
) -> pd.DataFrame:
    df = _exclude_partial_month(df)
    df = df.dropna(subset=[config.COL_RATE])

    group_cols = [config.COL_YEARMONTH]
    if group_by:
        group_cols.append(group_by)

    agg = (
        df.groupby(group_cols)[config.COL_RATE]
        .agg(median_rate="median", transaction_count="count")
        .reset_index()
    )
    agg = agg[agg["transaction_count"] >= min_transactions]
    agg[config.COL_YEARMONTH] = agg[config.COL_YEARMONTH].dt.to_timestamp()
    return agg.sort_values(config.COL_YEARMONTH)


@st.cache_data(max_entries=50)
def get_quarterly_volume(
    df: pd.DataFrame,
    group_by: str = None,
) -> pd.DataFrame:
    # Exclude the current partial quarter so an in-progress quarter (e.g. Q1 with
    # only Jan+Feb recorded) doesn't look like a volume collapse vs prior full quarters
    current_q_period = pd.Period(datetime.now(), freq="Q")
    df = df[df[config.COL_DATE].dt.to_period("Q") < current_q_period]

    group_cols = [config.COL_QUARTER]
    if group_by:
        group_cols.append(group_by)

    agg = (
        df.groupby(group_cols)
        .agg(
            transaction_count=(config.COL_PRICE, "count"),
            total_value_aed=(config.COL_PRICE, "sum"),
        )
        .reset_index()
    )
    return agg.sort_values(config.COL_QUARTER)


@st.cache_data(max_entries=50)
def get_district_heatmap_data(
    df: pd.DataFrame,
    min_transactions: int = config.DEFAULT_MIN_TRANSACTIONS,
) -> pd.DataFrame:
    df = df.dropna(subset=[config.COL_RATE])

    # Exclude the current year if it has fewer than 10 months of data recorded.
    # A partial year (e.g. only Jan–Mar) would appear as a full annual bar and make
    # that year look like a price collapse compared to prior complete years.
    current_year = pd.Timestamp.now().year
    max_month_in_curr_year = (
        df[df[config.COL_YEAR] == current_year][config.COL_DATE].dt.month.max()
        if current_year in df[config.COL_YEAR].values
        else 0
    )
    if max_month_in_curr_year < 10:
        df = df[df[config.COL_YEAR] < current_year]

    agg = (
        df.groupby([config.COL_DISTRICT, config.COL_YEAR])[config.COL_RATE]
        .agg(median_rate="median", transaction_count="count")
        .reset_index()
    )
    agg = agg[agg["transaction_count"] >= min_transactions]

    # YoY change per district — reindex to all years first to avoid
    # pct_change spanning non-consecutive years (e.g. 2019→2021 gap)
    all_years = sorted(agg[config.COL_YEAR].unique())
    rows = []
    for district, grp in agg.groupby(config.COL_DISTRICT):
        grp = grp.set_index(config.COL_YEAR).reindex(all_years)
        grp["median_rate"] = grp["median_rate"]  # NaN for missing years
        grp["yoy_change_pct"] = grp["median_rate"].pct_change(fill_method=None) * 100
        # Only keep rows that actually had data (not the reindex-injected NaN rows)
        grp = grp.dropna(subset=["transaction_count"])
        grp[config.COL_DISTRICT] = district
        grp = grp.reset_index().rename(columns={"index": config.COL_YEAR})
        rows.append(grp)

    if not rows:
        return pd.DataFrame()

    agg = pd.concat(rows, ignore_index=True)
    agg[config.COL_DISTRICT] = agg[config.COL_DISTRICT].str.title()
    return agg


@st.cache_data(max_entries=50)
def get_layout_price_distribution(
    df: pd.DataFrame,
    min_transactions: int = config.DEFAULT_MIN_TRANSACTIONS,
) -> pd.DataFrame:
    df = df.dropna(subset=[config.COL_RATE, config.COL_LAYOUT])
    agg = (
        df.groupby(config.COL_LAYOUT)[config.COL_RATE]
        .agg(
            median_rate="median",
            p25_rate=lambda x: x.quantile(0.25),
            p75_rate=lambda x: x.quantile(0.75),
            p10_rate=lambda x: x.quantile(0.10),
            p90_rate=lambda x: x.quantile(0.90),
            count="count",
        )
        .reset_index()
    )
    agg = agg[agg["count"] >= min_transactions]
    return agg


@st.cache_data(max_entries=50)
def get_price_band_distribution(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lo, hi, label in config.PRICE_BANDS:
        band_df = df[(df[config.COL_PRICE] >= lo) & (df[config.COL_PRICE] < hi)]
        by_type = band_df[config.COL_PROPERTY_TYPE].value_counts().reset_index()
        by_type.columns = ["property_type", "count"]
        by_type["price_band"] = label
        rows.append(by_type)
    if rows:
        return pd.concat(rows, ignore_index=True)
    return pd.DataFrame(columns=["price_band", "property_type", "count"])


@st.cache_data(max_entries=50)
def get_yoy_comparison(
    df: pd.DataFrame,
    min_transactions: int = config.DEFAULT_MIN_TRANSACTIONS,
    group_by: str | None = None,
    group_value: str | None = None,
) -> pd.DataFrame:
    """Monthly median rate grouped by year × month.

    Args:
        group_by: Optional column to filter on (e.g. COL_DISTRICT, COL_PROPERTY_TYPE, COL_LAYOUT).
        group_value: The specific value to filter to when group_by is set.
    """
    df = _exclude_partial_month(df)
    df = df.dropna(subset=[config.COL_RATE])
    if group_by and group_value:
        df = df[df[group_by] == group_value]
    agg = (
        df.groupby([config.COL_YEAR, config.COL_MONTH])[config.COL_RATE]
        .agg(median_rate="median", transaction_count="count")
        .reset_index()
    )
    agg = agg[agg["transaction_count"] >= min_transactions]
    return agg.sort_values([config.COL_YEAR, config.COL_MONTH])


@st.cache_data(max_entries=50)
def get_sale_type_monthly(df: pd.DataFrame) -> pd.DataFrame:
    # Exclude partial current month — prevents a sharp spurious drop at the chart's right edge
    df = _exclude_partial_month(df)
    df = df.dropna(subset=[config.COL_SALE_TYPE])
    df = df[df[config.COL_SALE_TYPE].isin(["off-plan", "ready"])]

    agg = (
        df.groupby([config.COL_YEARMONTH, config.COL_SALE_TYPE])
        .size()
        .reset_index(name="count")
    )
    agg[config.COL_YEARMONTH] = agg[config.COL_YEARMONTH].dt.to_timestamp()
    return agg.sort_values(config.COL_YEARMONTH)


@st.cache_data(max_entries=50)
def get_market_share_by_district(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    counts = df[config.COL_DISTRICT].str.title().value_counts().reset_index()
    counts.columns = ["district", "count"]
    top = counts.head(top_n)
    other_count = counts.iloc[top_n:]["count"].sum()
    if other_count > 0:
        top = pd.concat(
            [top, pd.DataFrame([{"district": "Other", "count": other_count}])],
            ignore_index=True,
        )
    return top


def compute_kpis(df: pd.DataFrame) -> dict:
    df = df.dropna(subset=[config.COL_RATE])
    df_sorted = df.sort_values(config.COL_DATE)

    # Anchor to last complete month to avoid partial-month distortion
    last_date = _last_complete_month_end(df_sorted)
    three_months_ago = last_date - pd.DateOffset(months=3)
    recent = df_sorted[df_sorted[config.COL_DATE] >= three_months_ago]
    current_rate = recent[config.COL_RATE].median() if len(recent) > 0 else None

    # YoY change — symmetric 3-month windows, both inclusive
    one_year_ago = last_date - pd.DateOffset(years=1)
    prior_year_start = one_year_ago - pd.DateOffset(months=3)
    prior = df_sorted[
        (df_sorted[config.COL_DATE] >= prior_year_start) &
        (df_sorted[config.COL_DATE] <= one_year_ago)
    ]
    prior_rate = prior[config.COL_RATE].median() if len(prior) > 0 else None
    yoy_change = None
    if current_rate is not None and prior_rate is not None and prior_rate > 0:
        yoy_change = (current_rate - prior_rate) / prior_rate * 100

    # 3-month momentum — compare last 3M vs previous 3M window
    six_months_ago = last_date - pd.DateOffset(months=6)
    three_months_mid = last_date - pd.DateOffset(months=3)
    prev_period = df_sorted[
        (df_sorted[config.COL_DATE] >= six_months_ago) &
        (df_sorted[config.COL_DATE] < three_months_mid)
    ]
    prev_rate = prev_period[config.COL_RATE].median() if len(prev_period) > 0 else None
    momentum = None
    if current_rate is not None and prev_rate is not None and prev_rate > 0:
        momentum = (current_rate - prev_rate) / prev_rate * 100

    return {
        "current_rate": current_rate,
        "yoy_change_pct": yoy_change,
        "momentum_pct": momentum,
        "total_transactions": len(df),
        "total_value_aed": df[config.COL_PRICE].sum(),
        "off_plan_share_pct": (
            (df[config.COL_SALE_TYPE] == "off-plan").sum() / len(df) * 100
            if len(df) > 0 else 0
        ),
    }


# ─────────────────────────────────────────────
# Tab 6: Project Intelligence
# ─────────────────────────────────────────────

@st.cache_data(max_entries=30)
def get_project_screener(
    df: pd.DataFrame,
    min_sales_12m: int = 10,
) -> pd.DataFrame:
    """
    Score every project against its district+type median.

    Returns one row per (project, district, property_type) with columns:
        project, district, property_type,
        median_rate, district_median, vs_district_pct,
        sales_12m, sales_3m, velocity_signal,
        rate_3m, rate_3m_prior, price_momentum_pct,
        signal  -- "promising" | "value_trap" | "neutral" | "insufficient"
    """
    df = df.dropna(subset=[config.COL_RATE, config.COL_PROJECT, config.COL_DATE])
    now = pd.Timestamp.now()
    cutoff_12m = now - pd.DateOffset(months=12)
    cutoff_3m = now - pd.DateOffset(months=3)
    cutoff_6m = now - pd.DateOffset(months=6)

    df_12m = df[df[config.COL_DATE] >= cutoff_12m]
    df_3m = df[df[config.COL_DATE] >= cutoff_3m]
    df_3m_prior = df[
        (df[config.COL_DATE] >= cutoff_6m) &
        (df[config.COL_DATE] < cutoff_3m)
    ]

    if df_12m.empty:
        return pd.DataFrame()

    # District+type median (last 12 months) — benchmark for all projects in that segment
    district_medians = (
        df_12m
        .groupby([config.COL_DISTRICT, config.COL_PROPERTY_TYPE])[config.COL_RATE]
        .median()
        .reset_index()
        .rename(columns={config.COL_RATE: "district_median"})
    )

    group_cols = [config.COL_PROJECT, config.COL_DISTRICT, config.COL_PROPERTY_TYPE]

    # 12-month aggregates
    agg_12m = (
        df_12m
        .groupby(group_cols)[config.COL_RATE]
        .agg(median_rate="median", sales_12m="count")
        .reset_index()
    )

    # 3-month counts
    agg_3m_count = (
        df_3m
        .groupby(group_cols)[config.COL_RATE]
        .agg(sales_3m="count", rate_3m="median")
        .reset_index()
    )

    # Prior 3-month median (3–6 months ago)
    agg_3m_prior = (
        df_3m_prior
        .groupby(group_cols)[config.COL_RATE]
        .median()
        .reset_index()
        .rename(columns={config.COL_RATE: "rate_3m_prior"})
    )

    # Merge everything
    result = agg_12m.merge(agg_3m_count, on=group_cols, how="left")
    result = result.merge(agg_3m_prior, on=group_cols, how="left")
    result = result.merge(district_medians, on=[config.COL_DISTRICT, config.COL_PROPERTY_TYPE], how="left")

    # Fill missing counts with 0
    result["sales_3m"] = result["sales_3m"].fillna(0).astype(int)

    # vs_district_pct: negative = below district = potential discount
    mask_dm = result["district_median"].notna() & (result["district_median"] > 0)
    result["vs_district_pct"] = np.nan
    result.loc[mask_dm, "vs_district_pct"] = (
        (result.loc[mask_dm, "median_rate"] - result.loc[mask_dm, "district_median"])
        / result.loc[mask_dm, "district_median"] * 100
    ).round(1)

    # velocity_signal: recent quarter vs average quarter over the past year
    # avg_quarter = sales_12m / 4; velocity = sales_3m / avg_quarter
    result["velocity_signal"] = np.nan
    mask_vel = result["sales_12m"] > 0
    result.loc[mask_vel, "velocity_signal"] = (
        result.loc[mask_vel, "sales_3m"] / (result.loc[mask_vel, "sales_12m"] / 4)
    ).round(2)

    # price_momentum_pct: 3M rate vs prior 3M rate
    mask_mom = result["rate_3m_prior"].notna() & (result["rate_3m_prior"] > 0) & result["rate_3m"].notna()
    result["price_momentum_pct"] = np.nan
    result.loc[mask_mom, "price_momentum_pct"] = (
        (result.loc[mask_mom, "rate_3m"] - result.loc[mask_mom, "rate_3m_prior"])
        / result.loc[mask_mom, "rate_3m_prior"] * 100
    ).round(1)

    # Signal classification
    def _classify(row):
        if row["sales_12m"] < min_sales_12m:
            return "insufficient"
        vs = row["vs_district_pct"]
        mom = row["price_momentum_pct"]
        vel = row["velocity_signal"]
        if pd.isna(vs) or pd.isna(mom):
            return "insufficient"
        # Value trap: very cheap but dying velocity
        if vs < -15 and pd.notna(vel) and vel < 0.7:
            return "value_trap"
        # Promising: discounted + rising momentum + enough volume
        if vs < -5 and mom > 0:
            return "promising"
        return "neutral"

    result["signal"] = result.apply(_classify, axis=1)

    # Rename for display
    result = result.rename(columns={
        config.COL_PROJECT: "project",
        config.COL_DISTRICT: "district",
        config.COL_PROPERTY_TYPE: "property_type",
    })

    return result.sort_values("vs_district_pct", ascending=True).reset_index(drop=True)


@st.cache_data(max_entries=30)
def get_project_monthly_rate(
    df: pd.DataFrame,
    project_name: str,
    min_transactions: int = 3,
) -> pd.DataFrame:
    """Monthly median rate for a specific project, broken down by layout if multiple exist."""
    df = _exclude_partial_month(df)
    df = df.dropna(subset=[config.COL_RATE])
    proj_df = df[df[config.COL_PROJECT] == project_name]

    if proj_df.empty:
        return pd.DataFrame()

    group_cols = [config.COL_YEARMONTH]
    layouts = proj_df[config.COL_LAYOUT].dropna().unique()
    has_layouts = len(layouts) > 1

    if has_layouts:
        group_cols.append(config.COL_LAYOUT)

    agg = (
        proj_df
        .groupby(group_cols)[config.COL_RATE]
        .agg(median_rate="median", transaction_count="count")
        .reset_index()
    )
    agg = agg[agg["transaction_count"] >= min_transactions]
    agg[config.COL_YEARMONTH] = agg[config.COL_YEARMONTH].dt.to_timestamp()
    return agg.sort_values(config.COL_YEARMONTH)


@st.cache_data(max_entries=30)
def get_project_district_monthly(
    df: pd.DataFrame,
    district: str,
    property_type: str,
    min_transactions: int = 5,
) -> pd.DataFrame:
    """Monthly median rate for the district+type — used as the reference line in deep dive."""
    df = _exclude_partial_month(df)
    df = df.dropna(subset=[config.COL_RATE])
    mask = (
        (df[config.COL_DISTRICT] == district) &
        (df[config.COL_PROPERTY_TYPE] == property_type)
    )
    district_df = df[mask]

    if district_df.empty:
        return pd.DataFrame()

    agg = (
        district_df
        .groupby(config.COL_YEARMONTH)[config.COL_RATE]
        .agg(district_median="median", transaction_count="count")
        .reset_index()
    )
    agg = agg[agg["transaction_count"] >= min_transactions]
    agg[config.COL_YEARMONTH] = agg[config.COL_YEARMONTH].dt.to_timestamp()
    return agg.sort_values(config.COL_YEARMONTH)


@st.cache_data(max_entries=30)
def get_project_quarterly_volume(
    df: pd.DataFrame,
    project_name: str,
) -> pd.DataFrame:
    """Quarterly transaction count for a specific project."""
    current_q_period = pd.Period(datetime.now(), freq="Q")
    proj_df = df[
        (df[config.COL_PROJECT] == project_name) &
        (df[config.COL_DATE].dt.to_period("Q") < current_q_period)
    ]
    if proj_df.empty:
        return pd.DataFrame()
    agg = (
        proj_df
        .groupby(config.COL_QUARTER)
        .agg(transaction_count=(config.COL_PRICE, "count"))
        .reset_index()
    )
    return agg.sort_values(config.COL_QUARTER)
