import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from statsmodels.tsa.seasonal import seasonal_decompose
from scipy import stats
import config


def _exclude_partial_month_analytics(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows in the current (potentially incomplete) calendar month."""
    current_period = pd.Period(datetime.now(), freq="M")
    return df[df[config.COL_DATE].dt.to_period("M") < current_period]


@dataclass
class DecompositionResult:
    observed: pd.Series
    trend: pd.Series
    seasonal: pd.Series
    residual: pd.Series
    model: str


def decompose_time_series(
    monthly_series: pd.Series,
    model: str = "additive",
) -> DecompositionResult:
    """
    Run seasonal decomposition on a monthly rate series.
    monthly_series: pd.Series with DatetimeIndex (monthly frequency), values = median rate.
    """
    series = monthly_series.copy()
    series.index = pd.DatetimeIndex(series.index).to_period("M").to_timestamp()
    series = series.asfreq("MS")

    # Fill short gaps (max 2 months) to handle sparse data
    series = series.interpolate(method="time", limit=2)

    result = seasonal_decompose(
        series,
        model=model,
        period=12,
        extrapolate_trend="freq",
    )
    return DecompositionResult(
        observed=result.observed,
        trend=result.trend,
        seasonal=result.seasonal,
        residual=result.resid,
        model=model,
    )


def compute_entry_signals(df: pd.DataFrame) -> dict:
    """
    7-step pipeline to compute best-time-to-enter signals from a filtered DataFrame.
    Returns a dict with signal DataFrame and metadata.
    """
    df = _exclude_partial_month_analytics(df)
    df = df.dropna(subset=[config.COL_RATE])

    # Step 1: Monthly aggregation
    monthly = (
        df.groupby(config.COL_YEARMONTH)[config.COL_RATE]
        .agg(median_rate="median", transaction_count="count")
        .reset_index()
    )
    monthly[config.COL_YEARMONTH] = monthly[config.COL_YEARMONTH].dt.to_timestamp()
    monthly = monthly.set_index(config.COL_YEARMONTH).sort_index()

    if len(monthly) < config.MIN_MONTHS_DECOMP_WARNING:
        return {
            "success": False,
            "reason": f"Insufficient data: {len(monthly)} months available, {config.MIN_MONTHS_DECOMP_WARNING} required.",
        }

    # Data quality flag: between 24 and 36 months, signals are possible but statistically fragile
    low_data_quality = len(monthly) < config.MIN_MONTHS_FOR_DECOMPOSITION

    # Step 2: Seasonal decomposition
    try:
        decomp = decompose_time_series(monthly["median_rate"], model="additive")
    except Exception as e:
        return {"success": False, "reason": f"Decomposition failed: {e}"}

    # Step 3 & 4: Average seasonal component by calendar month
    seasonal_series = decomp.seasonal.copy()
    seasonal_df = pd.DataFrame({
        "month": seasonal_series.index.month,
        "seasonal_value": seasonal_series.values,
    })
    seasonal_avg = seasonal_df.groupby("month")["seasonal_value"].mean()

    # Step 5: Normalize price signal (0=cheapest, 100=most expensive)
    s_min, s_max = seasonal_avg.min(), seasonal_avg.max()
    amplitude = s_max - s_min
    if amplitude == 0:
        price_signal = pd.Series(50.0, index=seasonal_avg.index)
    else:
        price_signal = (seasonal_avg - s_min) / amplitude * 100

    # Step 6: Volume competition score (0=least competition, 100=most)
    # High score = more buyers competing that month = worse entry conditions
    volume_monthly = monthly["transaction_count"].copy()
    # Use median (not mean) to suppress off-plan batch-registration spikes in specific months
    vol_by_month = pd.DataFrame({
        "month": volume_monthly.index.month,
        "count": volume_monthly.values,
    }).groupby("month")["count"].median()

    # Align to same 12 months
    all_months = pd.Index(range(1, 13), name="month")
    vol_by_month = vol_by_month.reindex(all_months, fill_value=vol_by_month.mean())
    price_signal = price_signal.reindex(all_months, fill_value=50.0)

    v_min, v_max = vol_by_month.min(), vol_by_month.max()
    if v_max == v_min:
        volume_competition_score = pd.Series(50.0, index=vol_by_month.index)
    else:
        volume_competition_score = (vol_by_month - v_min) / (v_max - v_min) * 100

    # Step 7: Composite signal (higher = worse entry; inverted to entry_score in charts)
    composite = (
        config.PRICE_SIGNAL_WEIGHT * price_signal +
        config.VOLUME_SIGNAL_WEIGHT * volume_competition_score
    )

    # Tier assignment (by percentile of the 12 composite values)
    p25, p50, p75 = composite.quantile([0.25, 0.50, 0.75])
    tiers = composite.apply(lambda v: (
        1 if v <= p25 else
        2 if v <= p50 else
        3 if v <= p75 else
        4
    ))

    signals = pd.DataFrame({
        "month": all_months,
        "month_name": [config.MONTH_NAMES[m - 1] for m in all_months],
        "price_signal": price_signal.values,
        "volume_competition_score": volume_competition_score.values,
        "composite_signal": composite.values,
        "tier": tiers.values,
        "tier_label": [config.TIER_LABELS[t] for t in tiers.values],
        "seasonal_adjustment_aed": seasonal_avg.reindex(all_months).values,
        "avg_monthly_volume": vol_by_month.values,
    })

    # Amplitude note
    if amplitude < config.AMPLITUDE_LOW_THRESHOLD:
        amplitude_note = f"Seasonal effect is small ({amplitude:,.0f} AED/SQM). Entry timing matters less."
    elif amplitude > config.AMPLITUDE_HIGH_THRESHOLD:
        amplitude_note = f"Strong seasonal effect ({amplitude:,.0f} AED/SQM). Entry timing is significant."
    else:
        amplitude_note = f"Moderate seasonal effect ({amplitude:,.0f} AED/SQM)."

    best_months = signals[signals["tier"] == 1]["month_name"].tolist()
    worst_months = signals[signals["tier"] == 4]["month_name"].tolist()

    return {
        "success": True,
        "signals": signals,
        "decomposition": decomp,
        "amplitude": amplitude,
        "amplitude_note": amplitude_note,
        "best_months": best_months,
        "worst_months": worst_months,
        "n_transactions": len(df),
        "year_span": f"{df[config.COL_DATE].dt.year.min()}–{df[config.COL_DATE].dt.year.max()}",
        "low_data_quality": low_data_quality,
        "n_months": len(monthly),
    }


def project_trend(
    trend_series: pd.Series,
    periods_ahead: int = config.PROJECTION_MONTHS,
    lookback_months: int = config.PROJECTION_LOOKBACK_MONTHS,
) -> dict:
    """
    Linear regression on trend component + projection with 95% CI.

    Uses only the most recent `lookback_months` of trend data for the fit so
    the 2020 COVID dip does not flatten what is actually a steep recent uptrend.
    Returns dict with full historical trend and projection DataFrames.
    """
    trend_clean = trend_series.dropna()
    if len(trend_clean) < 12:
        return {"success": False, "reason": "Insufficient trend data for projection."}

    # Restrict fit window to recent history; keep full series for the historical chart
    trend_fit = trend_clean.iloc[-lookback_months:] if len(trend_clean) > lookback_months else trend_clean

    x = np.arange(len(trend_fit))
    y = trend_fit.values

    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

    # Confidence interval (based on fit window)
    n = len(x)
    t_crit = stats.t.ppf(0.975, df=n - 2)
    x_mean = x.mean()
    s_err = np.sqrt(np.sum((y - (slope * x + intercept)) ** 2) / (n - 2))

    # Historical chart uses full trend series, fitted line only over the fit window
    hist_df = pd.DataFrame({
        "date": trend_clean.index,
        "trend_value": trend_clean.values,
        "fitted_value": float("nan"),
    })
    # Overlay the fitted line only on the lookback window
    fit_start_pos = len(trend_clean) - len(trend_fit)
    fitted = slope * x + intercept
    hist_df.loc[hist_df.index[fit_start_pos:], "fitted_value"] = fitted

    # Projection (continuing from end of fit window)
    proj_x = np.arange(len(trend_fit), len(trend_fit) + periods_ahead)
    proj_values = slope * proj_x + intercept

    # CI widens with distance from the fit data
    ci_margin = t_crit * s_err * np.sqrt(
        1 + 1 / n + (proj_x - x_mean) ** 2 / np.sum((x - x_mean) ** 2)
    )

    last_date = trend_clean.index[-1]
    proj_dates = pd.date_range(last_date, periods=periods_ahead + 1, freq="MS")[1:]

    proj_df = pd.DataFrame({
        "date": proj_dates,
        "projected_value": proj_values,
        "ci_lower": proj_values - ci_margin,
        "ci_upper": proj_values + ci_margin,
    })

    # Check for increasing variance in residuals (simple slope test on fit window)
    residuals = y - fitted
    resid_slope, _, _, resid_p, _ = stats.linregress(x, np.abs(residuals))
    high_uncertainty = resid_p < 0.05 and resid_slope > 0

    return {
        "success": True,
        "historical": hist_df,
        "projection": proj_df,
        "slope_per_month": slope,
        "r_squared": r_value ** 2,
        "high_uncertainty": high_uncertainty,
    }


def compute_momentum(monthly_series: pd.Series) -> pd.DataFrame:
    """
    Compute 3-month and 12-month momentum using rolling window medians.

    Receives a time-indexed series of monthly median rates (from get_monthly_median_rate).
    3M momentum: rolling-3 median of those monthly medians vs the prior rolling-3 window.
    12M momentum: rolling-3 median vs the rolling-3 window 12 months earlier.

    Note: compute_kpis() pools raw transactions over 3-month windows and takes a single
    median directly from raw data. This function operates on already-aggregated monthly
    medians, so small numerical differences from compute_kpis() are expected and normal.

    monthly_series: pd.Series indexed by datetime, values = median rate.
    """
    s = monthly_series.sort_index()
    df = pd.DataFrame({"rate": s})

    # Rolling 3-month median of the monthly medians (centred on the window endpoint)
    rolling = df["rate"].rolling(3).median()
    df["mom_3m"] = (rolling - rolling.shift(3)) / rolling.shift(3) * 100
    df["mom_12m"] = (rolling - rolling.shift(12)) / rolling.shift(12) * 100
    return df.dropna(subset=["mom_3m"])
