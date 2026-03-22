"""
pf_processor.py — Data processing layer for Property Finder listings.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, timezone, timedelta

SQFT_TO_SQM = 0.092903

# Bed string → layout string (matches CSV COL_LAYOUT values)
BEDS_TO_LAYOUT: dict[str, str] = {
    "Studio": "studio",
    "1 Bed": "1 bed",
    "2 Beds": "2 beds",
    "3 Beds": "3 beds",
    "4 Beds": "4 beds",
    "5 Beds": "5+ beds",
    "6 Beds": "6+ beds",
    "7 Beds": "6+ beds",
}

# Explicit reverse map (CSV layout → PF beds label) used for join key construction.
# Built explicitly to avoid dict-comprehension collision when multiple PF beds share a layout.
LAYOUT_TO_BEDS: dict[str, str] = {
    "studio": "Studio",
    "1 bed": "1 Bed",
    "2 beds": "2 Beds",
    "3 beds": "3 Beds",
    "4 beds": "4 Beds",
    "5+ beds": "5 Beds",
    "6+ beds": "6 Beds",
}

# PF district name → CSV lowercase district name
PF_DISTRICT_MAP: dict[str, str] = {
    "Saadiyat Island": "al saadiyat island",
    "Al Saadiyat Island": "al saadiyat island",
    "Yas Island": "yas island",
    "Al Reem Island": "al reem island",
    "Reem Island": "al reem island",
    "Al Reef": "al reef",
    "Al Shamkha": "al shamkhah",
    "Al Shamkhah": "al shamkhah",
    "Khalifa City": "khalifa city",
    "Zayed City": "zayed city",
    "Al Hidayriyyat Island": "al hidayriyyat",
    "Al Hudayriat Island": "al hidayriyyat",
    "Hidayriyyat Island": "al hidayriyyat",
    "Al Rahah": "al rahah",
    "Al Raha Beach": "al rahah",
    "Al Raha Gardens": "al rahah",
    "Al Raha Golf Gardens": "al rahah",
    "Al Falah": "al falah",
    "Mohamed Bin Zayed City": "mohamed bin zayed city",
    "Mohammed Bin Zayed City": "mohamed bin zayed city",
    "MBZ City": "mohamed bin zayed city",
    "Al Mushrif": "al mushrif",
    "Al Muroor": "al muroor",
    "Masdar City": "masdar city",
    "Al Ghadeer": "al ghadeer",
    "Al Jubail Island": "al jubail island",
    "Al Maryah Island": "al maryah island",
    "Maryah Island": "al maryah island",
    "Al Qurm": "al qurm",
    "Al Samha": "al samhah",
    "Al Bahya": "al bahyah",
    "Baniyas": "bani yas",
    "Ramhan Island": "ramhan island",
    "Fahid Island": "fahid island",
    "Rabdan": "rabdan",
    "Ghantoot": "ghantout",
    "The Marina": "al bateen",
    "Al Salam Street": "al danah",
}


def _normalise_district(pf_district: str) -> str:
    """Map PF district name to CSV lowercase district name."""
    # Direct map lookup
    if pf_district in PF_DISTRICT_MAP:
        return PF_DISTRICT_MAP[pf_district]
    # Lowercase direct match
    lower = pf_district.lower().strip()
    # Try with "al " prefix stripped for fuzzy fallback
    if lower.startswith("al "):
        stripped = lower[3:]
    else:
        stripped = lower
    # Return lowercase PF district as fallback (may not match CSV)
    return lower


def _normalise_type(pf_type: str) -> str:
    """Map PF property type string to CSV lowercase type."""
    t = pf_type.lower().strip()
    if "apartment" in t or "flat" in t:
        return "apartment"
    if "townhouse" in t or "attached villa" in t:
        return "townhouse / attached villa"
    if "villa" in t:
        return "villa"
    return t


@st.cache_data(ttl=3600)
def normalise_pf_listings(
    listings: list,
    cutoff_days: int = 30,
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """Convert raw PF listings list to a clean DataFrame.

    - sqft → sqm
    - Normalises district, type, beds
    - Filters to last cutoff_days relative to reference_date (defaults to now).
      Pass the snapshot's collected_at timestamp when processing historical snapshots
      so old snapshots are not filtered to empty by today's cutoff.
    """
    if not listings:
        return pd.DataFrame()

    rows = []
    ref = reference_date or datetime.now(tz=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    cutoff_dt = ref - timedelta(days=cutoff_days)

    for item in listings:
        price = item.get("price")
        area_sqft = item.get("area_sqft")
        price_per_sqft = item.get("price_per_sqft")

        if not price:
            continue

        # Date filter
        date_str = item.get("date", "")
        if date_str:
            try:
                listed_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if listed_dt < cutoff_dt:
                    continue
            except Exception:
                pass

        # sqft → sqm
        area_sqm = None
        if area_sqft:
            area_sqm = area_sqft * SQFT_TO_SQM

        # price_per_sqm
        price_per_sqm = None
        if area_sqm and area_sqm > 0:
            price_per_sqm = price / area_sqm
        elif price_per_sqft:
            price_per_sqm = price_per_sqft / SQFT_TO_SQM

        pf_district = item.get("district", "")
        pf_type = item.get("type", "")
        beds = item.get("beds", "Unknown")

        rows.append({
            "title":         item.get("title", ""),
            "price":         price,
            "area_sqft":     area_sqft,
            "area_sqm":      round(area_sqm, 1) if area_sqm else None,
            "price_per_sqft": price_per_sqft,
            "price_per_sqm": round(price_per_sqm, 0) if price_per_sqm else None,
            "beds":          beds,
            "layout":        BEDS_TO_LAYOUT.get(beds, beds.lower()),
            "pf_type":       pf_type,
            "type":          _normalise_type(pf_type),
            "pf_district":   pf_district,
            "district":      _normalise_district(pf_district),
            "community":     item.get("community", ""),
            "sale_type":     item.get("sale_type", ""),
            "date":          date_str,
            "url":           item.get("url", ""),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["price_per_sqm"])
    df = df[df["price_per_sqm"] > 0]
    return df.reset_index(drop=True)


def get_pf_snapshot_df(history: dict, snapshot_key: str) -> pd.DataFrame:
    """Extract one named snapshot from history as a normalised DataFrame."""
    for snap in history.get("snapshots", []):
        if snap.get("month") == snapshot_key:
            # Pass reference_date so historical snapshots are not filtered to empty
            ts = snap.get("collected_at", "")
            ref_date = None
            if ts:
                try:
                    from datetime import timezone as _tz
                    ref_date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if ref_date.tzinfo is None:
                        ref_date = ref_date.replace(tzinfo=_tz.utc)
                except Exception:
                    pass
            return normalise_pf_listings(snap.get("listings", []), reference_date=ref_date)
    return pd.DataFrame()


def build_asking_vs_actual(
    pf_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    min_listings: int = 3,
) -> pd.DataFrame:
    """Aggregate median asking price/sqm vs median actual price/sqm.

    Groups by (district, type, beds).
    Returns DataFrame with columns:
        district, type, beds, asking_median, actual_median, premium_pct, n_asking, n_actual
    """
    if pf_df.empty:
        return pd.DataFrame()

    # Aggregate asking prices
    asking = (
        pf_df
        .groupby(["district", "type", "beds"])
        .agg(asking_median=("price_per_sqm", "median"),
             n_asking=("price_per_sqm", "count"))
        .reset_index()
    )
    asking = asking[asking["n_asking"] >= min_listings]

    if asking.empty:
        return pd.DataFrame()

    # Aggregate actual prices from CSV — last 3 calendar months relative to today.
    # Using pd.Timestamp.now() (not the CSV's max date) ensures we always compare against
    # genuinely recent actuals and not stale data from months ago.
    from config import COL_DISTRICT, COL_PROPERTY_TYPE, COL_LAYOUT, COL_RATE, COL_DATE
    import pandas as _pd

    cutoff_3m = _pd.Timestamp.now() - _pd.DateOffset(months=3)
    actual_recent = actual_df[actual_df[COL_DATE] >= cutoff_3m]

    actual = (
        actual_recent
        .dropna(subset=[COL_RATE])
        .groupby([COL_DISTRICT, COL_PROPERTY_TYPE, COL_LAYOUT])
        .agg(actual_median=(COL_RATE, "median"),
             n_actual=(COL_RATE, "count"))
        .reset_index()
        .rename(columns={
            COL_DISTRICT: "district",
            COL_PROPERTY_TYPE: "type",
            COL_LAYOUT: "layout",
        })
    )

    # Use explicit LAYOUT_TO_BEDS map to avoid reverse-dict collision
    actual["beds"] = actual["layout"].map(LAYOUT_TO_BEDS).fillna(actual["layout"])

    # Enforce minimum transaction floor on actuals — prevents a single transaction
    # from defining the "actual median" that all asking prices are benchmarked against
    actual = actual[actual["n_actual"] >= min_listings]

    merged = asking.merge(
        actual[["district", "type", "beds", "actual_median", "n_actual"]],
        on=["district", "type", "beds"],
        how="left",
    )

    # Compute premium % — use np.nan (float dtype) not None (object dtype)
    mask = merged["actual_median"].notna() & (merged["actual_median"] > 0)
    merged["premium_pct"] = np.nan
    merged.loc[mask, "premium_pct"] = (
        (merged.loc[mask, "asking_median"] - merged.loc[mask, "actual_median"])
        / merged.loc[mask, "actual_median"] * 100
    ).round(1)

    return merged.reset_index(drop=True)


_MOM_GROUP_COLS = ["community", "district", "type", "beds"]


def build_mom_comparison(history: dict, min_listings: int = 3) -> pd.DataFrame:
    """Compare the latest two snapshots by (community, type, beds).

    Groups by community (project/development name) so only like-for-like units
    in the same project with the same type and bed count are compared.

    Returns DataFrame with columns:
        community, district, type, beds,
        prev_median, curr_median, n_prev, n_curr,
        mom_change_pct, alert, prev_samples, curr_samples
    """
    snapshots = history.get("snapshots", [])
    if len(snapshots) < 2:
        return pd.DataFrame()

    prev_snap = snapshots[-2]
    curr_snap = snapshots[-1]

    def _snap_ref_date(snap: dict) -> datetime | None:
        ts = snap.get("collected_at", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    prev_df = normalise_pf_listings(prev_snap.get("listings", []),
                                    reference_date=_snap_ref_date(prev_snap))
    curr_df = normalise_pf_listings(curr_snap.get("listings", []),
                                    reference_date=_snap_ref_date(curr_snap))

    if prev_df.empty or curr_df.empty:
        return pd.DataFrame()

    # Only compare listings where the project name is known
    prev_df = prev_df[prev_df["community"].str.strip() != ""].copy()
    curr_df = curr_df[curr_df["community"].str.strip() != ""].copy()

    if prev_df.empty or curr_df.empty:
        return pd.DataFrame()

    def _agg(df: pd.DataFrame) -> pd.DataFrame:
        return (
            df.groupby(_MOM_GROUP_COLS)
            .agg(median_rate=("price_per_sqm", "median"),
                 n=("price_per_sqm", "count"))
            .reset_index()
        )

    def _sample_listings(df: pd.DataFrame, n_samples: int = 3) -> dict:
        """Return up to n representative listings per group, sorted by price_per_sqm."""
        result: dict = {}
        for keys, grp in df.groupby(_MOM_GROUP_COLS):
            records = (
                grp.sort_values("price_per_sqm")
                .head(n_samples)[["title", "price", "area_sqm", "beds", "price_per_sqm", "url"]]
                .to_dict("records")
            )
            result[keys] = records
        return result

    prev_agg = _agg(prev_df)
    prev_agg = prev_agg[prev_agg["n"] >= min_listings]
    curr_agg = _agg(curr_df)
    curr_agg = curr_agg[curr_agg["n"] >= min_listings]

    if prev_agg.empty or curr_agg.empty:
        return pd.DataFrame()

    prev_samples = _sample_listings(prev_df)
    curr_samples = _sample_listings(curr_df)

    merged = curr_agg.merge(
        prev_agg[_MOM_GROUP_COLS + ["median_rate", "n"]].rename(
            columns={"median_rate": "prev_median", "n": "n_prev"}
        ),
        on=_MOM_GROUP_COLS,
        how="inner",
    ).rename(columns={"median_rate": "curr_median", "n": "n_curr"})

    mask = merged["prev_median"] > 0
    merged["mom_change_pct"] = np.nan
    merged.loc[mask, "mom_change_pct"] = (
        (merged.loc[mask, "curr_median"] - merged.loc[mask, "prev_median"])
        / merged.loc[mask, "prev_median"] * 100
    ).round(1)

    from config import PF_ALERT_DROP_PCT
    merged["alert"] = merged["mom_change_pct"].apply(
        lambda x: pd.notna(x) and x < PF_ALERT_DROP_PCT
    )

    def _get_samples(row: pd.Series, sample_dict: dict) -> list:
        key = tuple(row[c] for c in _MOM_GROUP_COLS)
        return sample_dict.get(key, [])

    merged["prev_samples"] = merged.apply(lambda r: _get_samples(r, prev_samples), axis=1)
    merged["curr_samples"] = merged.apply(lambda r: _get_samples(r, curr_samples), axis=1)

    return merged.reset_index(drop=True)


def get_snapshot_metadata(history: dict) -> list[dict]:
    """Return list of {key, date, count} for each snapshot — newest first."""
    snapshots = history.get("snapshots", [])
    result = []
    for s in snapshots:
        key = s.get("month", "")
        result.append({
            "key": key,
            "date": key,
            "count": s.get("listings_count", len(s.get("listings", []))),
        })
    return list(reversed(result))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _snap_reference_date(snap: dict) -> datetime | None:
    """Extract reference_date from a snapshot's collected_at timestamp."""
    ts = snap.get("collected_at", "")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _iter_normalised_snapshots(
    history: dict,
    snap_start: str | None = None,
    snap_end: str | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    """Iterate snapshots, normalise each with correct reference_date.

    Optionally filter to snapshots whose key falls within [snap_start, snap_end].
    Returns list of (snap_key, normalised_df) tuples.
    """
    results = []
    for snap in history.get("snapshots", []):
        key = snap.get("month", "")
        if snap_start and key < snap_start:
            continue
        if snap_end and key > snap_end:
            continue
        ref = _snap_reference_date(snap)
        df = normalise_pf_listings(snap.get("listings", []), reference_date=ref)
        if not df.empty:
            results.append((key, df))
    return results


# ── Asking Price Analysis functions ──────────────────────────────────────────

_TREND_GROUP_COLS = ["district", "type", "beds", "community"]


@st.cache_data(ttl=3600)
def build_asking_trend_series(
    history: dict,
    snap_start: str | None = None,
    snap_end: str | None = None,
    min_snapshots: int = 2,
) -> pd.DataFrame:
    """Build a time-series of median asking prices per segment across snapshots.

    Groups by (district, type, beds, community). Computes period-over-period
    and cumulative % change. Filters to segments appearing in >= min_snapshots.

    Returns DataFrame with columns:
        snap_date, district, type, beds, community,
        median_asking_rate, n_listings, pct_change_pop, pct_change_cumulative
    """
    snap_data = _iter_normalised_snapshots(history, snap_start, snap_end)
    if not snap_data:
        return pd.DataFrame()

    rows = []
    for snap_key, sdf in snap_data:
        agg = (
            sdf.groupby(_TREND_GROUP_COLS)["price_per_sqm"]
            .agg(["median", "count"])
            .reset_index()
            .rename(columns={"median": "median_asking_rate", "count": "n_listings"})
        )
        agg["snap_date"] = snap_key
        rows.append(agg)

    if not rows:
        return pd.DataFrame()

    trend = pd.concat(rows, ignore_index=True)

    # Filter to segments with data in >= min_snapshots
    seg_counts = trend.groupby(_TREND_GROUP_COLS)["snap_date"].nunique()
    valid = seg_counts[seg_counts >= min_snapshots].index
    trend = trend.set_index(_TREND_GROUP_COLS)
    trend = trend.loc[trend.index.isin(valid)].reset_index()

    if trend.empty:
        return trend

    # Sort for % change calculation
    trend = trend.sort_values(_TREND_GROUP_COLS + ["snap_date"]).reset_index(drop=True)

    # Period-over-period % change
    trend["pct_change_pop"] = (
        trend.groupby(_TREND_GROUP_COLS)["median_asking_rate"]
        .pct_change() * 100
    ).round(1)

    # Cumulative % change from first snapshot per segment
    first_vals = (
        trend.groupby(_TREND_GROUP_COLS)["median_asking_rate"]
        .transform("first")
    )
    mask = first_vals > 0
    trend["pct_change_cumulative"] = np.nan
    trend.loc[mask, "pct_change_cumulative"] = (
        (trend.loc[mask, "median_asking_rate"] - first_vals[mask]) / first_vals[mask] * 100
    ).round(1)

    return trend.reset_index(drop=True)


@st.cache_data(ttl=3600)
def build_asking_vs_actual_overlay(
    trend_series: pd.DataFrame,
    actual_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge asking trend series with monthly actual transaction medians.

    For each (district, type, beds) in the trend series, compute the monthly
    median actual rate from recent_sales.csv and align on a shared time axis.

    Returns DataFrame with columns:
        date, district, type, beds, community,
        median_asking_rate, median_actual_rate, premium_pct
    """
    from config import COL_DISTRICT, COL_PROPERTY_TYPE, COL_LAYOUT, COL_RATE, COL_DATE

    if trend_series.empty or actual_df.empty:
        return pd.DataFrame()

    # Build monthly actual medians grouped by (district, type, layout)
    act = actual_df.dropna(subset=[COL_RATE, COL_DATE]).copy()
    act["month"] = act[COL_DATE].dt.to_period("M").astype(str)
    act_agg = (
        act.groupby([COL_DISTRICT, COL_PROPERTY_TYPE, COL_LAYOUT, "month"])[COL_RATE]
        .agg(median_actual_rate="median", n_actual="count")
        .reset_index()
        .rename(columns={COL_DISTRICT: "district", COL_PROPERTY_TYPE: "type", COL_LAYOUT: "layout"})
    )

    # Map beds → layout for the join
    asking = trend_series.copy()
    asking["layout"] = asking["beds"].map(BEDS_TO_LAYOUT).fillna(asking["beds"].str.lower())
    # Convert snap_date (YYYY-MM-DD) to month period (YYYY-MM) for matching
    asking["month"] = asking["snap_date"].str[:7]

    merged = asking.merge(
        act_agg[["district", "type", "layout", "month", "median_actual_rate", "n_actual"]],
        on=["district", "type", "layout", "month"],
        how="left",
    )

    # Compute premium %
    mask = merged["median_actual_rate"].notna() & (merged["median_actual_rate"] > 0)
    merged["premium_pct"] = np.nan
    merged.loc[mask, "premium_pct"] = (
        (merged.loc[mask, "median_asking_rate"] - merged.loc[mask, "median_actual_rate"])
        / merged.loc[mask, "median_actual_rate"] * 100
    ).round(1)

    # Drop the helper layout column
    merged = merged.drop(columns=["layout"], errors="ignore")
    return merged.reset_index(drop=True)


def build_asking_recommendations(
    overlay_df: pd.DataFrame,
    drop_threshold: float | None = None,
    momentum_threshold: float | None = None,
) -> pd.DataFrame:
    """Flag segments with investment signals based on asking price trends.

    Signals:
      - buying_opportunity: cumulative % drop exceeds drop_threshold
      - below_market: current asking median < actual transaction median
      - momentum_premium: asking rising faster than actuals by > momentum_threshold

    Returns DataFrame with columns:
        district, type, beds, community, signal_type, detail_text, metric_value
    """
    from config import PF_TREND_DROP_THRESHOLD, PF_TREND_MOMENTUM_THRESHOLD

    if drop_threshold is None:
        drop_threshold = PF_TREND_DROP_THRESHOLD
    if momentum_threshold is None:
        momentum_threshold = PF_TREND_MOMENTUM_THRESHOLD

    if overlay_df.empty:
        return pd.DataFrame()

    signals = []
    group_cols = ["district", "type", "beds", "community"]

    for keys, grp in overlay_df.groupby(group_cols):
        district, ptype, beds, community = keys
        grp = grp.sort_values("snap_date")
        latest = grp.iloc[-1]

        # Signal 1: Buying opportunity — cumulative drop
        cum_change = latest.get("pct_change_cumulative")
        if pd.notna(cum_change) and cum_change < drop_threshold:
            signals.append({
                **dict(zip(group_cols, keys)),
                "signal_type": "buying_opportunity",
                "detail_text": (
                    f"Asking prices dropped {cum_change:+.1f}% since first tracked — "
                    f"potential buying opportunity"
                ),
                "metric_value": cum_change,
            })

        # Signal 2: Below market — asking < actual
        asking = latest.get("median_asking_rate")
        actual = latest.get("median_actual_rate")
        if pd.notna(asking) and pd.notna(actual) and actual > 0 and asking < actual:
            gap_pct = ((asking - actual) / actual * 100)
            signals.append({
                **dict(zip(group_cols, keys)),
                "signal_type": "below_market",
                "detail_text": (
                    f"Asking price is {gap_pct:.1f}% below recent transaction prices"
                ),
                "metric_value": round(gap_pct, 1),
            })

        # Signal 3: Momentum premium — asking rising faster than actuals
        if pd.notna(asking) and pd.notna(actual) and actual > 0:
            premium = latest.get("premium_pct")
            # Check if premium is growing: compare first and last premium
            first_row = grp.dropna(subset=["premium_pct"])
            if len(first_row) >= 2:
                first_premium = first_row.iloc[0]["premium_pct"]
                latest_premium = first_row.iloc[-1]["premium_pct"]
                if pd.notna(first_premium) and pd.notna(latest_premium):
                    momentum_gap = latest_premium - first_premium
                    if momentum_gap > momentum_threshold:
                        signals.append({
                            **dict(zip(group_cols, keys)),
                            "signal_type": "momentum_premium",
                            "detail_text": (
                                f"Asking prices rising {momentum_gap:.1f}% faster than "
                                f"actuals — momentum premium building"
                            ),
                            "metric_value": round(momentum_gap, 1),
                        })

    if not signals:
        return pd.DataFrame()

    return pd.DataFrame(signals)
