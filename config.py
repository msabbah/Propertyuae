# Column name constants
COL_ASSET_CLASS = "Asset Class"
COL_PROPERTY_TYPE = "Property Type"
COL_DATE = "Sale Application Date"
COL_AREA_SQM = "Property Sold Area (SQM)"
COL_LAND_AREA = "Land Plot Ground Area (SQM)"
COL_LAYOUT = "Property Layout"
COL_DISTRICT = "District"
COL_COMMUNITY = "Community"
COL_PROJECT = "Project Name"
COL_PRICE = "Property Sale Price (AED)"
COL_SHARE = "Property Sold Share"
COL_RATE = "Rate (AED per SQM)"
COL_SALE_TYPE = "Sale Application Type"
COL_SEQUENCE = "Sale Sequence"

# Derived column names
COL_YEAR = "Year"
COL_MONTH = "Month"
COL_YEARMONTH = "YearMonth"
COL_QUARTER = "Quarter"

# Focus property types (display names → lowercase CSV values)
FOCUS_PROPERTY_TYPES = ["apartment", "villa", "townhouse / attached villa"]
PROPERTY_TYPE_LABELS = {
    "apartment": "Apartment",
    "villa": "Villa",
    "townhouse / attached villa": "Townhouse",
}

# Top districts by volume
TOP_DISTRICTS = [
    "Al Reem Island",
    "Yas Island",
    "Al Saadiyat Island",
    "Al Reef",
    "Al Shamkhah",
    "Khalifa City",
    "Zayed City",
    "Al Hidayriyyat",
    "Al Rahah",
    "Al Faqa'",
]

# Cleaning thresholds
PRICE_MIN_AED = 200_000          # Minimum credible residential transaction price
RATE_MIN_AED_SQM = 1_000         # Minimum credible rate — filters sub-1k/sqm distorted rows
RATE_OUTLIER_PERCENTILE_LOW = 1
RATE_OUTLIER_PERCENTILE_HIGH = 99
PRICE_OUTLIER_PERCENTILE_HIGH = 99

# Minimum transactions to show a data point (suppresses noise)
DEFAULT_MIN_TRANSACTIONS = 10

# Minimum months required for seasonal decomposition
# 36 = 3 full annual cycles — minimum for statistically reliable seasonal components
MIN_MONTHS_FOR_DECOMPOSITION = 36
# Warn user if between this threshold and MIN_MONTHS_FOR_DECOMPOSITION
MIN_MONTHS_DECOMP_WARNING = 24

# Trend projection horizon
PROJECTION_MONTHS = 6
# Only use this many recent months of trend data for the linear projection fit
# Prevents the 2020 COVID dip from averaging down what is actually a steep recent uptrend
PROJECTION_LOOKBACK_MONTHS = 30

# Seasonal signal weights
PRICE_SIGNAL_WEIGHT = 0.6
VOLUME_SIGNAL_WEIGHT = 0.4

# Seasonal amplitude thresholds (AED/SQM)
AMPLITUDE_LOW_THRESHOLD = 500
AMPLITUDE_HIGH_THRESHOLD = 2000

# Colors
PROPERTY_TYPE_COLORS = {
    "apartment": "#4e79a7",
    "villa": "#f28e2b",
    "townhouse / attached villa": "#59a14f",
}

DISTRICT_COLORS = {
    "al reem island": "#1f77b4",
    "yas island": "#ff7f0e",
    "al saadiyat island": "#2ca02c",
    "al reef": "#d62728",
    "al shamkhah": "#9467bd",
    "khalifa city": "#8c564b",
    "zayed city": "#e377c2",
    "al hidayriyyat": "#17becf",
    "al rahah": "#7f7f7f",
    "al faqa'": "#bcbd22",
}

TIER_COLORS = {
    1: "#1a9641",   # Best Entry  - dark green  (ColorBrewer RdYlGn-4)
    2: "#a6d96a",   # Good        - light green
    3: "#fdae61",   # Neutral     - amber
    4: "#d7191c",   # Avoid       - red
}

TIER_LABELS = {
    1: "Best Entry",
    2: "Good",
    3: "Neutral",
    4: "Avoid",
}

SALE_TYPE_COLORS = {
    "off-plan": "#8e44ad",
    "ready": "#16a085",
}

# Price bands for distribution chart
PRICE_BANDS = [
    (0, 1_000_000, "< 1M"),
    (1_000_000, 2_000_000, "1M – 2M"),
    (2_000_000, 5_000_000, "2M – 5M"),
    (5_000_000, 10_000_000, "5M – 10M"),
    (10_000_000, float("inf"), "10M+"),
]

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Market state classification thresholds (used in classify_market_state)
# Calibrated to Abu Dhabi historical volatility (1 sigma ≈ 2–3% YoY)
MARKET_STATE_STRONG_YOY = 3.0       # % YoY threshold for "strong growth"
MARKET_STATE_STRONG_MOM = 1.0       # % momentum threshold for "strong growth"
MARKET_STATE_DECLINE_YOY = -3.0     # % YoY threshold for "caution/declining"
MARKET_STATE_DECLINE_MOM = -1.0     # % momentum threshold for "caution/declining"

# ── Property Finder integration ──────────────────────────────────────────────
SQFT_TO_SQM = 0.092903
PF_CUTOFF_DAYS = 30          # Only include listings from last 30 days
PF_MAX_PAGES = 60
PF_RATE_SLEEP = 1.2
PF_MIN_LISTINGS = 5          # Min listings per segment to show in comparison (median of 3 is statistically unreliable)
PF_ALERT_DROP_PCT = -3.0     # Alert threshold for MoM asking price drop (%)

# ── Asking Price Analysis tab ────────────────────────────────────────────────
PF_TREND_DROP_THRESHOLD = -5.0       # Cumulative % drop to flag as buying opportunity
PF_TREND_MOMENTUM_THRESHOLD = 5.0    # % gap between asking and actual growth rates for momentum premium
PF_TREND_MIN_SNAPSHOTS = 2           # Minimum snapshots for a segment to appear in trends
