# Requirements: Asking Price Analysis Tab

**Tab Name:** Asking Price Analysis
**Status:** Approved for execution
**Intensity:** 4 — Deep
**Estimated Complexity:** High (~480 new/modified lines across 4 files)
**Date:** 2026-03-22

---

## Overview

Rebuild the current Asking Price Trends section (Section F in Tab 5 "Asking vs Actual") into a standalone, full-featured **Asking Price Analysis** tab. The tab gives investors a clear, filterable view of how Property Finder asking prices evolve over time, how they compare to actual transaction prices, and where opportunities or risks exist.

**Data sources:**
- `pf_history.json` — dated snapshots of scraped PF listings
- `pf_cache.json` — 24h scrape cache
- `recent_sales.csv` — actual transaction data (~95,222 residential rows)

**Files affected:**
- `app.py` — new tab + rewritten Section F
- `pf_processor.py` — 3 new aggregation functions
- `charts.py` — 4 new chart factory functions
- `config.py` — new constants

---

## Requirements

### R1 — Snapshot Time-Range Selector

**Given** the user opens the Asking Price Analysis tab,
**When** the tab loads,
**Then** a time-range selector is displayed with quick-select presets as `st.radio()`: "Last 7 days", "Last 30 days" (default), "Last 90 days", "All", "Custom". Selecting "Custom" reveals a date range picker. All charts and data below are filtered to the selected range.

A subtitle must display: *"Showing data from [start] to [end] ([N] listings across [M] snapshots)"*.

**Test:** Load tab → verify "Last 30 days" is pre-selected. Click each preset → verify charts update and subtitle reflects the new range. Click "Custom" → verify date pickers appear and selection works.

---

### R2 — Fix reference_date Bug (Blocker)

**Given** old snapshots exist in `pf_history.json` (e.g., 60+ days old),
**When** the trend section iterates snapshots to build the time series,
**Then** each call to `normalise_pf_listings()` must pass `reference_date` extracted from `snap["collected_at"]`, matching the pattern already used in `get_pf_snapshot_df()` (`pf_processor.py` lines 196–208).

Without this fix, old snapshots are silently filtered to empty by the 30-day cutoff relative to today.

**Test:** With 3+ snapshots spanning 90 days, select "All" in the time range. Verify all snapshots contribute data to charts (no empty gaps).

---

### R3 — Granular Grouping with Cascading Filters

**Given** PF listings contain district, type, beds, and community fields,
**When** the user interacts with the filter panel,
**Then** cascading filters are provided in this order:

1. **District** — multiselect, default "All"
2. **Property Type** — selectbox, default "Apartment", options narrowed to types available in selected district(s)
3. **Layout / Beds** — multiselect, default "All", options narrowed to beds available in selected district(s) + type
4. **Community / Project** — multiselect, default "All", options narrowed to communities available in selected district(s) + type + beds

Each filter label must show the count of matching listings, e.g., *"Community (47 listings)"*.

**"Comparable properties"** are defined as listings sharing the same **(district + type + layout/beds)** combination. Community adds a further drill-down within comparables.

**Test:** Select district "Al Reem Island" → verify type dropdown narrows. Select type "Villa" → verify beds dropdown narrows to villa layouts only. Verify listing counts update. Reset to "All" → verify all options reappear.

---

### R4 — Percentage Change Calculations

**Given** at least 2 snapshots exist for a segment (district + type + beds + community),
**When** the trend series is built,
**Then** compute:

- **(a) Period-over-period % change:** `(current_median - previous_median) / previous_median * 100` for every consecutive pair of snapshots.
- **(b) Cumulative % change:** `(current_median - first_median) / first_median * 100` from the first snapshot in the selected range.

**Implementation:** New function `build_asking_trend_series()` in `pf_processor.py` with `@st.cache_data`. Returns DataFrame with columns:

| Column | Type | Description |
|--------|------|-------------|
| `snap_date` | str | Snapshot key (YYYY-MM-DD) |
| `district` | str | Normalised district name |
| `type` | str | Property type |
| `beds` | str | Layout/beds label |
| `community` | str | Project/community name |
| `median_asking_rate` | float | Median price per sqm |
| `n_listings` | int | Number of listings in this group |
| `pct_change_pop` | float | Period-over-period % change |
| `pct_change_cumulative` | float | Cumulative % change from first snapshot |

Segments with fewer than `config.PF_TREND_MIN_SNAPSHOTS` (default: 2) snapshots are excluded.

**Test:** With 4 snapshots, verify `pct_change_pop` for snapshot 3 = `(median_3 - median_2) / median_2 * 100`. Verify `pct_change_cumulative` for snapshot 4 = `(median_4 - median_1) / median_1 * 100`. Verify segments with only 1 snapshot are excluded.

---

### R5 — Asking vs Actual Price Overlay

**Given** a segment is selected via filters,
**When** the asking-vs-actual chart renders,
**Then** it displays on a single chart:

- **Asking prices:** Scatter + line at snapshot dates (median asking rate per sqm)
- **Actual transaction prices:** Continuous line of monthly median rate from `recent_sales.csv` for the matching segment (`COL_DISTRICT` + `COL_PROPERTY_TYPE` + `COL_LAYOUT`)
- **Gap visualisation:** Shaded area or annotation between the two lines highlighting premium (asking > actual) or discount (asking < actual)

The join between PF and CSV data must use the `BEDS_TO_LAYOUT` mapping in `pf_processor.py` for the beds-to-layout key.

**Implementation:** New function `build_asking_vs_actual_overlay()` in `pf_processor.py` with `@st.cache_data`.

**Test:** Select a segment with both PF snapshots and actual transactions. Verify both lines appear on the chart. Verify gap shading is visible. Verify the actual line uses median (not mean).

---

### R6 — Chart Specifications

All charts must be factory functions in `charts.py` following the `fig_*()` naming convention and existing Plotly patterns (hover templates, `config.*` colors, consistent height/margin).

| Chart | Function | Type | Purpose |
|-------|----------|------|---------|
| **A** | `fig_asking_trend_line()` | Multi-line + markers | Median asking rate per segment over snapshot dates, with % change annotations |
| **B** | `fig_asking_vs_actual_trend()` | Overlay (scatter+line vs line) | Asking snapshots vs actual monthly median, with gap shading |
| **C** | `fig_asking_pct_change_bar()` | Bar chart | Period-over-period % change per segment per snapshot. Green = drop, red = rise |
| **D** | `fig_asking_cumulative_line()` | Indexed line | Cumulative % change from first snapshot (base = 0%) |

**Test:** Each chart renders without error. Hover tooltips show formatted values (AED with commas, % with 1 decimal). Colors match `config.py` constants. Charts handle edge cases (single snapshot → single point, no actuals → asking line only).

---

### R7 — Drill-Down with Expandable Detail

**Given** the user wants to validate the tool's calculations,
**When** they select a segment and expand the detail section,
**Then** an `st.expander("View underlying data")` shows:

1. **Listings table** — Individual PF listings from each snapshot for that segment (title, price, area sqm, price/sqm, beds, community, sale type, URL as clickable link, snapshot date). Sortable by price/sqm.
2. **Summary stats table** — Per snapshot: median, count, min, max, and IQR of `price_per_sqm`.
3. **Actual comparables table** — Matching transactions from `recent_sales.csv` for the same district + type + layout within the same time window. Columns: date, price, area, rate, sale sequence.
4. **Download button** — CSV export of the listings table.

**Test:** Expand the detail section. Verify all 3 tables render. Verify listing URLs are clickable. Verify summary stats match manual calculation. Verify actual comparables use the correct segment match. Verify CSV download works.

---

### R8 — Upgrade Recommendations

**Given** the trend series and asking-vs-actual comparison are computed,
**When** the recommendations section renders,
**Then** display in an `st.expander("Investment Signals", expanded=True)`:

| Signal | Condition | Label | Color |
|--------|-----------|-------|-------|
| **Buying opportunity** | Cumulative % change < `config.PF_TREND_DROP_THRESHOLD` (default: -5.0%) | "Asking prices have dropped [X]% — potential buying opportunity" | Green |
| **Below market** | Current asking median < actual transaction median | "Asking price is [X]% below recent transaction prices" | Green |
| **Momentum premium** | Asking prices rising faster than actuals by > `config.PF_TREND_MOMENTUM_THRESHOLD` (default: 5.0%) | "Asking prices rising [X]% faster than actuals — momentum premium" | Amber |

Each recommendation must identify the segment (district, type, beds, community) and link to its drill-down.

**Implementation:** New function `build_asking_recommendations()` in `pf_processor.py`. Returns DataFrame with columns: `district, type, beds, community, signal_type, detail_text, metric_value`.

**Test:** Create test data with a segment that dropped 8%. Verify "buying opportunity" signal appears. Verify a segment where asking < actual shows "below market". Verify threshold constants from `config.py` are respected.

---

### R9 — Data Persistence (No Schema Change)

**Given** the existing `pf_history.json` structure:
```json
{
  "snapshots": [
    {
      "month": "YYYY-MM-DD",
      "collected_at": "ISO-8601",
      "listings_count": N,
      "listings": [
        {
          "title": "...", "price": N, "area_sqft": N,
          "price_per_sqft": N, "beds": "...", "type": "...",
          "district": "...", "community": "...",
          "sale_type": "...", "date": "...", "url": "..."
        }
      ]
    }
  ]
}
```
**Then** no schema change is required. All new functions aggregate on the fly from this existing store. The scraper (`pf_scraper.py`) already captures all required fields.

**Test:** Verify existing `pf_history.json` works with the new functions without migration.

---

### R10 — Code Architecture Compliance

- No inline Plotly chart code in `app.py`. All figures built in `charts.py`.
- All data aggregation in `pf_processor.py` with `@st.cache_data` decorators.
- All new constants in `config.py`.
- `app.py` contains only Streamlit layout, filters, and calls to processor/chart functions.
- All new widget keys use `pf_trend_` prefix to avoid collisions.

**Test:** Search `app.py` for `go.Figure()` in the Asking Price Analysis section — must return zero matches. Search for hardcoded column name strings — must return zero. All chart calls must reference `charts.fig_*()` functions.

---

### R11 — User-Friendly UI

#### R11a — Smart Defaults: Zero-Config First View

The tab must render fully on first load with no user interaction. Default filters: all snapshots (last 30 days), all districts, apartment, all beds, all communities. All 4 charts and KPI cards must display populated data.

**Test:** Open tab without touching any filter. Verify all charts render with data. No empty states or "select a filter" prompts.

#### R11b — Progressive Disclosure: Summary First, Detail on Demand

Layout hierarchy:
1. **Top (no scroll):** KPI metric cards — current median asking price, MoM % change, total listings, asking-vs-actual gap
2. **Middle:** The 4 main charts
3. **Bottom:** Expanders for drill-down detail and recommendations

No expander is open by default except "Investment Signals" (R8).

**Test:** Load tab. Verify KPIs are visible without scrolling. Verify drill-down expanders are collapsed. Verify expanding them does not displace KPIs.

#### R11c — Cascading Filters with Instant Feedback

(Covered in R3.) Additionally: no valid filter combination may produce an empty-data state. If a combination would be empty, that option must not appear in the downstream dropdown.

**Test:** Rapidly click through filter combinations. Verify no combination produces a broken or empty chart (data too sparse is handled by R11f instead).

#### R11d — Dynamic Investor Takeaway Captions

Each chart displays a data-driven `st.caption()` with at least one number from the current selection. Examples:
- *"Asking prices in Al Reem dropped 4.2% MoM — potential negotiation leverage."*
- *"Asking is AED 1,230/sqm above actual — sellers pricing 8.1% above market."*
- *"Only 12 listings match — thin market, verify with broker."*

If data is insufficient: *"Not enough data for a reliable signal — broaden your filters."*

**Test:** For each chart, verify caption is present, contains a real number, and updates when filters change.

#### R11e — Consistent Visual Language

- Colors from `config.py` (green = positive/growth, red = negative/decline, amber = neutral/caution)
- `st.divider()` between major sections
- `st.columns()` with same ratios as existing tabs
- Number formatting: AED with comma separators, no decimals; % to 1 decimal with +/- sign; areas in SQM with commas
- Plotly chart styling matches existing `charts.py` patterns (template, fonts, gridlines, hover format)

**Test:** Compare visual style with Tab 1 (Price History). Colors, formatting, and chart styling must be indistinguishable.

#### R11f — Graceful Empty & Low-Data States

When a filter combination returns fewer than `config.PF_MIN_LISTINGS` results:
- Charts do not render (no empty/broken charts)
- `st.info()` appears in place of each chart: *"Not enough listings for [Chart Name] — try broadening your filters."*
- KPI cards show "—" instead of NaN or 0
- Recommendations section shows: *"Insufficient data for recommendations."*

**Test:** Select a narrow filter combination with <5 listings. Verify no chart renders, info messages appear, KPIs show "—", no tracebacks.

#### R11g — Snapshot Presets

(Covered in R1.) Quick-select radio buttons with "Last 30 days" as default and subtitle showing current range and listing count.

#### R11h — Responsive Column Layout

- KPI cards: 4 equal columns in one row
- Chart pairs: 2 columns at 1:1 ratio
- Asking-vs-actual chart (R6-B): full width (needs space for overlay)
- No chart narrower than 400px effective width

**Test:** Load at 1280px browser width. Verify KPIs are legible, paired charts have equal width, overlay chart is full-width, no horizontal scrollbar.

---

## Config Constants (to add to `config.py`)

| Constant | Default | Purpose |
|----------|---------|---------|
| `PF_TREND_DROP_THRESHOLD` | `-5.0` | Cumulative % drop to flag as buying opportunity |
| `PF_TREND_MOMENTUM_THRESHOLD` | `5.0` | % gap between asking and actual growth rates to flag momentum premium |
| `PF_TREND_MIN_SNAPSHOTS` | `2` | Minimum snapshots for a segment to appear in trends |

---

## Execution Plan

| Step | Agent | Model | Task | Depends On | Output |
|------|-------|-------|------|------------|--------|
| 1 | `python-pro` | sonnet | Fix `reference_date` bug (R2) | — | `app.py` |
| 2 | `python-pro` | sonnet | Add config constants (R10) | — | `config.py` |
| 3 | `python-pro` | opus | Build `build_asking_trend_series()` (R4) | 1, 2 | `pf_processor.py` |
| 4 | `python-pro` | opus | Build `build_asking_vs_actual_overlay()` (R5) | 3 | `pf_processor.py` |
| 5 | `python-pro` | opus | Build `build_asking_recommendations()` (R8) | 3, 4 | `pf_processor.py` |
| 6 | `python-pro` | opus | Create 4 chart factories (R6) | 3, 4 | `charts.py` |
| 7 | `python-pro` | opus | Rewrite tab UI (R1, R3, R7, R11) | 1–6 | `app.py` |
| 8 | `python-pro` | sonnet | Update imports | 7 | `app.py` |
| 9 | `debugger` | sonnet | Verify all charts, filters, edge cases, no regressions | 7, 8 | Test report |

**Parallel groups:** Steps 1+2 | Steps 4+5 | Rest sequential
**Review checkpoints:** After Step 3, After Step 6, After Step 7

---

## Risks & Considerations

1. **Sparse data per segment** — (district, type, beds, community) is very granular. UI should allow toggling between "by community" and "by district" aggregation level.
2. **Snapshot volume scaling** — 50+ snapshots could be slow. Mitigate with `@st.cache_data`.
3. **District name mismatch** — `PF_DISTRICT_MAP` doesn't cover all PF names. Show "no actual data" gracefully.
4. **Widget key collisions** — All new keys use `pf_trend_` prefix.
5. **reference_date bug is a blocker** — Must be Step 1.

---

## Skill Candidates

1. **`/normalize-snapshots`** — Snapshot iteration with `reference_date` pattern appears 3+ times. Extract to shared helper.
2. **`/cascading-filters`** — District → type → beds → community filter cascade is reusable across tabs.
