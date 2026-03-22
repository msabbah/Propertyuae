import pandas as pd
import numpy as np
import streamlit as st
from pathlib import Path
import config

DATA_PATH   = Path(__file__).parent / "recent_sales.csv"
MERGED_PATH = Path(__file__).parent / "merged_sales.csv"

# Columns used to fingerprint a unique transaction for deduplication
_DEDUP_COLS = [
    config.COL_DATE,
    config.COL_DISTRICT,
    config.COL_COMMUNITY,
    config.COL_PROJECT,
    config.COL_PRICE,
    config.COL_AREA_SQM,
]


def _build_dedup_key(df: pd.DataFrame) -> pd.Series:
    """Build a string fingerprint for each row using key identifying columns."""
    parts = []
    for col in _DEDUP_COLS:
        if col in df.columns:
            parts.append(df[col].astype(str).str.strip().str.lower())
        else:
            parts.append(pd.Series([""] * len(df), index=df.index))
    return parts[0].str.cat(parts[1:], sep="|")


def clean_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the full cleaning pipeline to a raw transactions DataFrame.

    Works on any DataFrame with the expected column schema — whether loaded
    from the bundled CSV or uploaded by the user.
    """
    df = df.copy()

    # Strip whitespace from string columns
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].str.strip()

    # Parse date
    df[config.COL_DATE] = pd.to_datetime(df[config.COL_DATE], errors="coerce")
    df = df.dropna(subset=[config.COL_DATE])

    # Filter to fully-owned transactions (sold_share == 1.0)
    df[config.COL_SHARE] = pd.to_numeric(df[config.COL_SHARE], errors="coerce")
    df = df[df[config.COL_SHARE] == 1.0]

    # Filter valid sale sequence
    df[config.COL_SEQUENCE] = df[config.COL_SEQUENCE].astype(str).str.strip().str.lower()
    df = df[df[config.COL_SEQUENCE].isin({"primary", "secondary"})]

    # Normalize string columns to lowercase
    for col in [config.COL_ASSET_CLASS, config.COL_PROPERTY_TYPE,
                config.COL_DISTRICT, config.COL_LAYOUT, config.COL_SALE_TYPE]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().str.strip()

    # Filter to residential only
    df = df[df[config.COL_ASSET_CLASS] == "residential"]

    # Permanently exclude court-mandated sales (distressed assets, median ~4,200 AED/sqm)
    df = df[df[config.COL_SALE_TYPE] != "court-mandated"]

    # Drop rows where unit area AND rate are both null
    df[config.COL_RATE] = pd.to_numeric(df[config.COL_RATE], errors="coerce")
    df[config.COL_AREA_SQM] = pd.to_numeric(df[config.COL_AREA_SQM], errors="coerce")
    df = df[~(df[config.COL_AREA_SQM].isna() & df[config.COL_RATE].isna())]

    # Recalculate null Rate/SQM from Price / Area
    df[config.COL_PRICE] = pd.to_numeric(df[config.COL_PRICE], errors="coerce")
    mask_null_rate = (
        df[config.COL_RATE].isna() &
        df[config.COL_AREA_SQM].notna() &
        (df[config.COL_AREA_SQM] > 0)
    )
    df.loc[mask_null_rate, config.COL_RATE] = (
        df.loc[mask_null_rate, config.COL_PRICE] / df.loc[mask_null_rate, config.COL_AREA_SQM]
    )

    # Drop rows missing price
    df = df.dropna(subset=[config.COL_PRICE])
    df = df[df[config.COL_PRICE] >= config.PRICE_MIN_AED]

    # Price outlier removal per property type (99th percentile within each type)
    # Global cap would let villa prices set a cap that clips valid high-end apartments, or vice versa
    keep_price_idx = []
    for ptype, group in df.groupby(config.COL_PROPERTY_TYPE):
        price_cap = group[config.COL_PRICE].quantile(config.PRICE_OUTLIER_PERCENTILE_HIGH / 100)
        keep_price_idx.extend(group[group[config.COL_PRICE] <= price_cap].index.tolist())
    df = df.loc[keep_price_idx]

    # Hard rate floor — removes physically impossible low values before percentile outlier removal
    df = df[df[config.COL_RATE].isna() | (df[config.COL_RATE] >= config.RATE_MIN_AED_SQM)]

    # Rate outlier removal per property type (1st–99th percentile within each type)
    keep_idx = []
    for ptype, group in df.groupby(config.COL_PROPERTY_TYPE):
        lo = group[config.COL_RATE].quantile(config.RATE_OUTLIER_PERCENTILE_LOW / 100)
        hi = group[config.COL_RATE].quantile(config.RATE_OUTLIER_PERCENTILE_HIGH / 100)
        keep_idx.extend(group[
            group[config.COL_RATE].isna() |
            ((group[config.COL_RATE] >= lo) & (group[config.COL_RATE] <= hi))
        ].index.tolist())
    df = df.loc[keep_idx]

    # Derive time columns
    df[config.COL_YEAR] = df[config.COL_DATE].dt.year
    df[config.COL_MONTH] = df[config.COL_DATE].dt.month
    df[config.COL_QUARTER] = df[config.COL_DATE].dt.to_period("Q").astype(str)
    df[config.COL_YEARMONTH] = df[config.COL_DATE].dt.to_period("M")

    return df.reset_index(drop=True)


def save_merged(df: pd.DataFrame) -> None:
    """Write the merged DataFrame to merged_sales.csv so it survives page refreshes."""
    df.to_csv(MERGED_PATH, index=False, encoding="utf-8-sig")


def load_merged_if_exists() -> pd.DataFrame | None:
    """Return the persisted merged dataset if it exists, otherwise None."""
    if not MERGED_PATH.exists():
        return None
    try:
        df = pd.read_csv(MERGED_PATH, encoding="utf-8-sig")
        df[config.COL_DATE] = pd.to_datetime(df[config.COL_DATE], errors="coerce")
        df[config.COL_YEARMONTH] = df[config.COL_DATE].dt.to_period("M")
        return df
    except Exception:
        return None


def delete_merged() -> None:
    """Remove the persisted merged dataset (revert to original CSV)."""
    if MERGED_PATH.exists():
        MERGED_PATH.unlink()


def merge_transactions(df_existing: pd.DataFrame, df_new: pd.DataFrame) -> pd.DataFrame:
    """Merge a new transactions DataFrame into the existing one, deduplicating rows.

    Strategy:
    - Fingerprint every row with a composite key of date + district + community +
      project + price + area.
    - Append only rows from df_new whose fingerprint is not already in df_existing.
    - Returns the combined DataFrame sorted by date.

    The new rows are NOT re-run through outlier removal (they were already cleaned).
    """
    if df_existing.empty:
        return df_new.reset_index(drop=True)
    if df_new.empty:
        return df_existing.reset_index(drop=True)

    existing_keys = set(_build_dedup_key(df_existing))
    new_keys = _build_dedup_key(df_new)
    is_new = ~new_keys.isin(existing_keys)
    new_only = df_new[is_new]

    if new_only.empty:
        return df_existing.reset_index(drop=True)

    merged = pd.concat([df_existing, new_only], ignore_index=True)
    merged = merged.sort_values(config.COL_DATE).reset_index(drop=True)
    return merged


@st.cache_data(ttl=3600, show_spinner="Loading and cleaning data...")
def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig")
    return clean_raw_df(df)


@st.cache_data
def get_filter_options(df: pd.DataFrame) -> dict:
    """Return available filter options from cleaned data."""
    districts = sorted(df[config.COL_DISTRICT].str.title().unique().tolist())
    property_types = sorted(df[config.COL_PROPERTY_TYPE].unique().tolist())
    layouts = sorted(df[config.COL_LAYOUT].dropna().unique().tolist())
    sale_types = sorted(df[config.COL_SALE_TYPE].dropna().unique().tolist())
    years = sorted(df[config.COL_YEAR].unique().tolist())
    return {
        "districts": districts,
        "property_types": property_types,
        "layouts": layouts,
        "sale_types": sale_types,
        "years": years,
    }
