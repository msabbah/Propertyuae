"""
build_mashvisor.py  — Generates index.html (Mashvisor-style dual-page dashboard)
Run: python3 build_mashvisor.py
"""
import json
import time
import re as _re
import pandas as pd
import numpy as np
from pathlib import Path
try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

BASE_DIR = Path(__file__).parent
DATA_PATH     = BASE_DIR / "recent_sales.csv"
OUTPUT_PATH   = BASE_DIR / "index.html"
PF_CACHE_PATH   = BASE_DIR / "pf_cache.json"
PF_HISTORY_PATH = BASE_DIR / "pf_history.json"
PF_CUTOFF_DAYS = 90   # filter out listings older than 90 days
PF_MAX_PAGES   = 60   # 60 pages × ~20 listings = ~1200 listings
PF_RATE_SLEEP  = 1.2
PF_BASE_URL    = "https://www.propertyfinder.ae/en/buy/abu-dhabi/properties-for-sale.html"

ALLOWED_PROPERTY_TYPES = {"apartment", "villa", "townhouse / attached villa"}

# ─── Column constants (mirrors config.py) ──────────────────────────────────────
COL_DATE       = "Sale Application Date"
COL_ASSET      = "Asset Class"
COL_TYPE       = "Property Type"
COL_AREA_SQM   = "Property Sold Area (SQM)"
COL_LAND_AREA  = "Land Plot Ground Area (SQM)"
COL_LAYOUT     = "Property Layout"
COL_DISTRICT   = "District"
COL_COMMUNITY  = "Community"
COL_PROJECT    = "Project Name"
COL_PRICE      = "Property Sale Price (AED)"
COL_SHARE      = "Property Sold Share"
COL_RATE       = "Rate (AED per SQM)"
COL_SALE_TYPE  = "Sale Application Type"
COL_SEQUENCE   = "Sale Sequence"

# ─── Data loading (standalone, no streamlit) ────────────────────────────────────
def load_data() -> pd.DataFrame:
    print("Loading CSV…")
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig")

    # Strip whitespace
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Parse date
    df[COL_DATE] = pd.to_datetime(df[COL_DATE], errors="coerce")
    df = df.dropna(subset=[COL_DATE])

    # Filter sold share == 1.0
    df[COL_SHARE] = pd.to_numeric(df[COL_SHARE], errors="coerce")
    df = df[df[COL_SHARE] == 1.0]

    # Filter valid sale sequence
    df[COL_SEQUENCE] = df[COL_SEQUENCE].astype(str).str.strip().str.lower()
    df = df[df[COL_SEQUENCE].isin({"primary", "secondary"})]

    # Normalize string cols
    for col in [COL_ASSET, COL_TYPE, COL_DISTRICT, COL_LAYOUT, COL_SALE_TYPE]:
        df[col] = df[col].astype(str).str.lower().str.strip()

    # Residential only
    df = df[df[COL_ASSET] == "residential"]

    # Remove court-mandated sales
    df = df[df[COL_SALE_TYPE] != "court-mandated"]

    # Keep only apartment / villa / townhouse (strips land plots, farms, etc.)
    df = df[df[COL_TYPE].isin(ALLOWED_PROPERTY_TYPES)]

    # Drop missing area
    df = df.dropna(subset=[COL_AREA_SQM, COL_LAND_AREA], how="all")

    # Numeric conversions
    for col in [COL_RATE, COL_AREA_SQM, COL_PRICE]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fill null rates
    mask = df[COL_RATE].isna() & df[COL_AREA_SQM].notna() & (df[COL_AREA_SQM] > 0)
    df.loc[mask, COL_RATE] = df.loc[mask, COL_PRICE] / df.loc[mask, COL_AREA_SQM]

    # Drop missing price
    df = df.dropna(subset=[COL_PRICE])
    df = df[df[COL_PRICE] >= 50_000]

    # Price outlier removal (global 99th pct)
    price_cap = df[COL_PRICE].quantile(0.99)
    df = df[df[COL_PRICE] <= price_cap]

    # Rate outlier removal per property type
    keep_idx = []
    for ptype, group in df.groupby(COL_TYPE):
        lo = group[COL_RATE].quantile(0.01)
        hi = group[COL_RATE].quantile(0.99)
        keep_idx.extend(group[
            group[COL_RATE].isna() |
            ((group[COL_RATE] >= lo) & (group[COL_RATE] <= hi))
        ].index.tolist())
    df = df.loc[keep_idx]

    # Derived columns
    df["Year"]      = df[COL_DATE].dt.year
    df["Month"]     = df[COL_DATE].dt.month
    df["YearMonth"] = df[COL_DATE].dt.to_period("M").astype(str)
    df["Quarter"]   = df[COL_DATE].dt.to_period("Q").astype(str)

    df = df.reset_index(drop=True)
    print(f"  Loaded {len(df):,} rows after cleaning.")
    return df


# ─── Serialization helpers ──────────────────────────────────────────────────────
def fmt_date(ts) -> str:
    try:
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return ""

def safe_int(v):
    if pd.isna(v): return None
    return int(round(v))

def safe_float(v, decimals=0):
    if pd.isna(v): return None
    return round(float(v), decimals)


# ─── Table data serialization ───────────────────────────────────────────────────
def build_table_data(df: pd.DataFrame) -> list:
    """Compact JSON rows with short field aliases."""
    print("Building table data…")
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "d":  fmt_date(r[COL_DATE]),
            "di": str(r[COL_DISTRICT]).title()  if pd.notna(r[COL_DISTRICT])  else "",
            "co": str(r[COL_COMMUNITY]).title() if pd.notna(r[COL_COMMUNITY]) else "",
            "pr": str(r[COL_PROJECT])           if pd.notna(r[COL_PROJECT])   else "",
            "ty": str(r[COL_TYPE]).title()      if pd.notna(r[COL_TYPE])      else "",
            "la": str(r[COL_LAYOUT]).title()    if pd.notna(r[COL_LAYOUT])    else "",
            "p":  safe_int(r[COL_PRICE]),
            "a":  safe_float(r[COL_AREA_SQM], 1),
            "r":  safe_int(r[COL_RATE]),
            "st": str(r[COL_SALE_TYPE])         if pd.notna(r[COL_SALE_TYPE]) else "",
        })
    print(f"  {len(rows):,} table rows serialized.")
    return rows



# ─── Property Finder Scraper ──────────────────────────────────────────────────
def _pf_fmt_beds(val) -> str:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return "Unknown"
    if n == 0:
        return "Studio"
    return f"{n} Bed" + ("s" if n > 1 else "")

def _pf_district(path_name: str) -> str:
    """Extract district from 'Abu Dhabi, District, Sub-area' path_name."""
    parts = [p.strip() for p in path_name.split(",")]
    meaningful = [p for p in parts if p.lower() != "abu dhabi"]
    return meaningful[0] if meaningful else path_name

def _pf_parse_page(html: str) -> list:
    nd_m = _re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, _re.DOTALL)
    if not nd_m:
        return []
    try:
        nd = json.loads(nd_m.group(1))
        raw_listings = (nd.get("props", {})
                          .get("pageProps", {})
                          .get("searchResult", {})
                          .get("listings", []))
    except Exception:
        return []

    results = []
    for item in raw_listings:
        if item.get("listing_type") != "property":
            continue
        prop = item.get("property") or {}

        price = None
        try:
            price = int((prop.get("price") or {}).get("value") or 0) or None
        except (TypeError, ValueError):
            pass
        if not price:
            continue

        area_sqft = None
        try:
            area_sqft = float((prop.get("size") or {}).get("value") or 0) or None
        except (TypeError, ValueError):
            pass

        price_per_sqft = None
        try:
            price_per_sqft = int((prop.get("price_per_area") or {}).get("price") or 0) or None
        except (TypeError, ValueError):
            pass

        loc = prop.get("location") or {}
        community = loc.get("name") or ""
        path_name = loc.get("path_name") or ""
        district  = _pf_district(path_name) if path_name else community

        completion = (prop.get("completion_status") or "").lower()
        sale_type = "off-plan" if "off_plan" in completion else "ready"

        details_path = prop.get("details_path") or prop.get("share_url") or ""
        url = ("https://www.propertyfinder.ae" + details_path) if details_path.startswith("/") else details_path

        results.append({
            "title":          (prop.get("title") or "").strip(),
            "price":          price,
            "area_sqft":      round(area_sqft) if area_sqft else None,
            "price_per_sqft": price_per_sqft,
            "beds":           _pf_fmt_beds(prop.get("bedrooms_value")),
            "type":           prop.get("property_type") or "Other",
            "district":       district,
            "community":      community,
            "sale_type":      sale_type,
            "date":           prop.get("listed_date") or "",
            "url":            url,
        })
    return results

def fetch_propertyfinder() -> list:
    from datetime import datetime, timezone, timedelta

    # Check 24h cache
    if PF_CACHE_PATH.exists():
        try:
            cached = json.loads(PF_CACHE_PATH.read_text(encoding="utf-8"))
            age_h = (time.time() - cached.get("ts", 0)) / 3600
            if age_h < 24:
                print(f"  PF: cache hit — {len(cached['listings']):,} listings ({age_h:.1f}h old)")
                return cached["listings"]
        except Exception:
            pass

    if not _HAS_REQUESTS:
        print("  PF: requests library not installed — skipping scrape")
        return []

    print(f"  PF: fetching {PF_MAX_PAGES} pages from propertyfinder.ae (Abu Dhabi, for sale)…")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=PF_CUTOFF_DAYS)
    all_listings = []
    seen_ids = set()

    for page in range(1, PF_MAX_PAGES + 1):
        # Use sort=nd (Newest) to get most recent listings first
        url = f"{PF_BASE_URL}?sort=nd&page={page}"
        try:
            resp = _requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 404:
                print(f"    page {page}: 404 — no more pages")
                break
            if resp.status_code != 200:
                print(f"    page {page}: HTTP {resp.status_code} — stopping")
                break
            items = _pf_parse_page(resp.text)
            if not items:
                print(f"    page {page}: no listings parsed — stopping")
                break

            # Deduplicate and filter by cutoff date
            page_listings = []
            for r in items:
                uid = r.get("url") or r.get("title", "")
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                # Exclude listings older than PF_CUTOFF_DAYS
                if r["date"]:
                    try:
                        listed_dt = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                        if listed_dt < cutoff_dt:
                            continue  # skip old listing but keep paging
                    except Exception:
                        pass
                page_listings.append(r)

            all_listings.extend(page_listings)
            print(f"    page {page}: {len(page_listings)} kept / {len(items)} on page  (total {len(all_listings):,})")
            time.sleep(PF_RATE_SLEEP)

        except Exception as exc:
            print(f"    page {page}: error — {exc}")
            break

    try:
        PF_CACHE_PATH.write_text(
            json.dumps({"ts": time.time(), "listings": all_listings},
                       ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"  PF: cache write error — {e}")

    print(f"  PF: done — {len(all_listings):,} listings fetched")
    return all_listings


# ─── HTML Template ──────────────────────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Abu Dhabi Real Estate Intelligence</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<link href="https://cdn.datatables.net/2.0.3/css/dataTables.dataTables.min.css" rel="stylesheet"/>
<style>
/* ── Reset & variables ── */
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#FAF9F6;
  --bg2:#F5F0E8;
  --surface:#FFFFFF;
  --border:#E8E2D9;
  --border-lite:#F0EBE3;
  --txt:#1A1714;
  --txt2:#6B6560;
  --txt3:#A8A29C;
  --accent:#D4761A;
  --accent-h:#B8611A;
  --accent-bg:#FDF3E7;
  --nav:#1A1714;
  --success:#15803D;
  --danger:#DC2626;
  --sh:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
  --sh-md:0 4px 14px rgba(0,0,0,.08),0 2px 4px rgba(0,0,0,.04);
  --r:10px;--r-sm:6px;--r-lg:14px;
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;-webkit-font-smoothing:antialiased}

/* ── Navbar ── */
.navbar{background:var(--nav);height:54px;display:flex;align-items:center;padding:0 20px;position:sticky;top:0;z-index:1000;gap:24px;border-bottom:1px solid rgba(255,255,255,.06)}
.navbar .brand{font-weight:700;font-size:15px;letter-spacing:-.4px;color:#fff;display:flex;align-items:center;gap:9px;flex-shrink:0}
.brand-mark{width:20px;height:20px;background:var(--accent);border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#fff;letter-spacing:-.5px;flex-shrink:0}
.nav-tabs{display:flex;gap:1px;height:100%}
.nav-tab{display:flex;align-items:center;padding:0 14px;cursor:pointer;font-size:13px;font-weight:500;color:rgba(255,255,255,.45);border-bottom:2px solid transparent;transition:all .18s;text-decoration:none;letter-spacing:-.1px}
.nav-tab:hover{color:rgba(255,255,255,.8)}
.nav-tab.active{color:#fff;border-bottom-color:var(--accent)}
.nav-spacer{flex:1}
.nav-badge{background:rgba(255,255,255,.08);color:rgba(255,255,255,.6);border-radius:999px;padding:2px 10px;font-size:11px;font-weight:500;border:1px solid rgba(255,255,255,.1)}

/* ── Pages ── */
.page{display:none}.page.active{display:block}

/* ══ PAGE 1 — EXPLORER ══ */
.explorer-layout{display:flex;height:calc(100vh - 54px);overflow:hidden}

/* Sidebar */
.sidebar{width:244px;min-width:244px;background:var(--surface);border-right:1px solid var(--border);overflow-y:auto;display:flex;flex-direction:column;flex-shrink:0}
.sidebar::-webkit-scrollbar{width:3px}
.sidebar::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.sb-head{display:flex;align-items:center;justify-content:space-between;padding:13px 16px 11px;border-bottom:1px solid var(--border-lite);flex-shrink:0}
.sb-title{font-size:10px;font-weight:600;color:var(--txt2);text-transform:uppercase;letter-spacing:.7px;display:flex;align-items:center;gap:6px}
.sb-clear{font-size:11px;font-weight:500;color:var(--txt3);background:none;border:none;cursor:pointer;font-family:inherit;padding:0;transition:color .15s}
.sb-clear:hover{color:var(--danger)}

/* Sidebar search */
.sb-search-wrap{padding:10px 12px;border-bottom:1px solid var(--border-lite);position:relative;flex-shrink:0}
.sb-search-wrap svg{position:absolute;left:21px;top:50%;transform:translateY(-50%);color:var(--txt3);pointer-events:none}
.sb-search{width:100%;border:1px solid var(--border);border-radius:var(--r-sm);padding:8px 10px 8px 32px;font-size:12px;font-family:inherit;outline:none;color:var(--txt);background:var(--bg);transition:all .15s}
.sb-search::placeholder{color:var(--txt3)}
.sb-search:focus{border-color:var(--accent);background:var(--surface);box-shadow:0 0 0 3px rgba(212,118,26,.1)}

/* Accordion sections */
.fs{border-bottom:1px solid var(--border-lite);flex-shrink:0}
.fs-head{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;cursor:pointer;user-select:none;transition:background .12s}
.fs-head:hover{background:#FDFCF9}
.fs-head-left{display:flex;align-items:center;gap:7px}
.fs-title{font-size:10px;font-weight:600;color:var(--txt2);text-transform:uppercase;letter-spacing:.7px}
.fs-badge{background:var(--accent);color:#fff;border-radius:999px;font-size:9px;font-weight:700;padding:1px 6px;line-height:15px;display:none}
.fs-chevron{font-size:8px;color:var(--txt3);transition:transform .2s}
.fs.open .fs-chevron{transform:rotate(180deg)}
.fs-body{display:none;padding-bottom:6px}
.fs.open .fs-body{display:block}

/* Section action row */
.cl-acts{display:flex;gap:10px;padding:5px 16px 3px}
.cl-act{font-size:10px;font-weight:600;color:var(--accent);background:none;border:none;cursor:pointer;padding:0;font-family:inherit;transition:color .12s;text-transform:uppercase;letter-spacing:.2px}
.cl-act:hover{color:var(--accent-h);text-decoration:underline}
.cl-act.dim{color:var(--txt3)}.cl-act.dim:hover{color:var(--danger)}

/* District search */
.cl-search{display:block;width:calc(100% - 32px);margin:5px 16px 2px;border:1px solid var(--border);border-radius:var(--r-sm);padding:5px 9px;font-size:12px;font-family:inherit;outline:none;color:var(--txt);background:var(--bg)}
.cl-search:focus{border-color:var(--accent)}
.cl-list{max-height:180px;overflow-y:auto}
.cl-list::-webkit-scrollbar{width:3px}
.cl-list::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* Checklist items */
.cl-item{display:flex;align-items:center;gap:8px;padding:5px 16px;cursor:pointer;transition:background .1s}
.cl-item:hover{background:var(--accent-bg)}
.cl-item input[type=checkbox]{width:13px;height:13px;accent-color:var(--accent);cursor:pointer;flex-shrink:0}
.cl-item-label{font-size:12px;color:var(--txt2);cursor:pointer;flex:1;line-height:1.3}
.cl-item-count{font-size:10px;color:var(--txt3);white-space:nowrap}
.cl-item.on .cl-item-label{color:var(--accent);font-weight:600}
.cl-item.on .cl-item-count{color:#E8A060}
.cl-item.on{background:var(--accent-bg)}

/* Date range */
.sb-dates{padding:4px 16px 10px;display:flex;flex-direction:column;gap:8px}
.sb-date-group{display:flex;flex-direction:column;gap:3px}
.sb-date-lbl{font-size:9px;font-weight:600;color:var(--txt3);text-transform:uppercase;letter-spacing:.7px}
.sb-date-in{width:100%;border:1px solid var(--border);border-radius:var(--r-sm);padding:7px 8px;font-size:12px;font-family:inherit;outline:none;cursor:pointer;color:var(--txt);background:var(--bg);transition:border-color .15s}
.sb-date-in:focus{border-color:var(--accent)}

/* Main content */
.main-content{flex:1;overflow-y:auto;background:var(--bg);display:flex;flex-direction:column;min-width:0}
.main-content::-webkit-scrollbar{width:5px}
.main-content::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* KPI strip */
.kpi-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:16px 20px 12px;flex-shrink:0}
.kpi-tile{background:var(--surface);border-radius:var(--r);padding:14px 16px;box-shadow:var(--sh);display:flex;align-items:center;gap:12px;border:1px solid var(--border-lite);transition:box-shadow .15s}
.kpi-tile:hover{box-shadow:var(--sh-md)}
.kpi-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:15px}
.kpi-icon.blue{background:var(--accent-bg)}
.kpi-icon.green{background:#ECFDF5}
.kpi-icon.amber{background:#FFFBEB}
.kpi-icon.violet{background:#F5F3FF}
.kpi-val{font-size:18px;font-weight:700;color:var(--txt);line-height:1.1;letter-spacing:-.5px}
.kpi-lbl{font-size:10px;color:var(--txt3);margin-top:2px;font-weight:500;text-transform:uppercase;letter-spacing:.3px}

/* Table area */
.table-area{padding:0 20px 24px;flex:1}
.table-toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.table-info{font-size:13px;color:var(--txt2);display:flex;align-items:center;gap:8px}
.table-info strong{color:var(--txt);font-weight:700}
.result-badge{background:var(--accent-bg);color:var(--accent);border-radius:999px;padding:2px 9px;font-size:11px;font-weight:600;border:1px solid rgba(212,118,26,.15)}

/* Export button */
.btn-export{display:inline-flex;align-items:center;gap:6px;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);padding:7px 14px;font-size:12px;font-weight:500;cursor:pointer;color:var(--txt2);font-family:inherit;transition:all .15s}
.btn-export:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-bg)}
.btn-export svg{color:var(--txt3)}.btn-export:hover svg{color:var(--accent)}

/* Card & DataTable */
.card{background:var(--surface);border-radius:var(--r);box-shadow:var(--sh);overflow:hidden;border:1px solid var(--border-lite)}
table.dataTable{width:100%!important;border-collapse:collapse!important}
table.dataTable thead th{background:var(--bg);color:var(--txt3);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;padding:10px 14px!important;border-bottom:1px solid var(--border)!important;white-space:nowrap;cursor:pointer;user-select:none}
table.dataTable thead th:hover{color:var(--txt2)}
table.dataTable thead th.sorting_asc::after{content:' ↑';opacity:.5}
table.dataTable thead th.sorting_desc::after{content:' ↓';opacity:.5}
table.dataTable tbody td{padding:10px 14px!important;font-size:13px;border-bottom:1px solid var(--border-lite)!important;color:var(--txt);vertical-align:middle}
table.dataTable tbody tr:last-child td{border-bottom:none!important}
table.dataTable tbody tr:hover td{background:var(--accent-bg)!important}
.badge{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600}
.badge-offplan{background:#FDF3E7;color:#B8611A;border:1px solid rgba(212,118,26,.2)}
.badge-ready{background:#ECFDF5;color:#15803D;border:1px solid rgba(21,128,61,.2)}
/* ── DataTables unified UI ── */
.dt-top{display:flex;align-items:center;justify-content:space-between;padding:12px 16px 10px;border-bottom:1px solid var(--border-lite);gap:12px;flex-wrap:wrap}
div.dataTables_wrapper div.dataTables_length label{font-size:12px;color:var(--txt3);display:flex;align-items:center;gap:7px;white-space:nowrap;font-family:inherit}
div.dataTables_wrapper div.dataTables_length select{border:1px solid var(--border);border-radius:var(--r-sm);padding:4px 26px 4px 10px;font-size:12px;font-family:inherit;font-weight:500;outline:none;color:var(--txt);cursor:pointer;-webkit-appearance:none;appearance:none;background:var(--surface) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='9' height='5' viewBox='0 0 9 5'%3E%3Cpath d='M0 0l4.5 5L9 0z' fill='%23A8A29C'/%3E%3C/svg%3E") no-repeat right 8px center;box-shadow:var(--sh);transition:border-color .15s}
div.dataTables_wrapper div.dataTables_length select:hover{border-color:var(--accent-h)}
div.dataTables_wrapper div.dataTables_length select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(212,118,26,.1)}
div.dataTables_wrapper div.dataTables_filter label{display:flex;align-items:center;position:relative}
div.dataTables_wrapper div.dataTables_filter input[type=search]{border:1px solid var(--border);border-radius:var(--r-sm);padding:6px 10px 6px 32px;font-size:12px;font-family:inherit;outline:none;color:var(--txt);width:200px;transition:all .18s;background:var(--bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='13' viewBox='0 0 20 20' fill='none' stroke='%23A8A29C' stroke-width='2.2'%3E%3Ccircle cx='9' cy='9' r='6'/%3E%3Cpath d='M15 15l3 3'/%3E%3C/svg%3E") no-repeat 9px center}
div.dataTables_wrapper div.dataTables_filter input[type=search]:focus{border-color:var(--accent);background-color:var(--surface);box-shadow:0 0 0 3px rgba(212,118,26,.1);width:240px}
div.dataTables_wrapper div.dataTables_filter input[type=search]::placeholder{color:var(--txt3)}
.dt-foot{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-top:1px solid var(--border-lite);flex-wrap:wrap;gap:8px}
div.dataTables_wrapper div.dataTables_info{font-size:12px;color:var(--txt3);font-family:inherit;display:flex;align-items:center}
div.dataTables_wrapper div.dataTables_paginate{display:flex;align-items:center;gap:3px}
div.dataTables_paginate .paginate_button{border-radius:var(--r-sm)!important;font-size:12px!important;padding:5px 10px!important;border:none!important;background:transparent!important;color:var(--txt2)!important;cursor:pointer!important;transition:all .12s!important;line-height:1.4!important}
div.dataTables_paginate .paginate_button:hover:not(.disabled):not(.current){background:var(--bg)!important;color:var(--txt)!important}
div.dataTables_paginate .paginate_button.current{background:var(--accent)!important;color:#fff!important;font-weight:600!important}
div.dataTables_paginate .paginate_button.disabled{opacity:.4!important;cursor:default!important}
div.dataTables_paginate .paginate_button.previous,div.dataTables_paginate .paginate_button.next{background:var(--surface)!important;border:1px solid var(--border)!important;color:var(--txt2)!important;font-weight:500!important;padding:5px 13px!important}
div.dataTables_paginate .paginate_button.previous:hover:not(.disabled),div.dataTables_paginate .paginate_button.next:hover:not(.disabled){background:var(--accent-bg)!important;border-color:var(--accent)!important;color:var(--accent)!important}
div.dataTables_paginate .paginate_button.previous.disabled,div.dataTables_paginate .paginate_button.next.disabled{background:var(--bg)!important;border-color:var(--border-lite)!important}

/* ── Analytics Page ── */
#page-analytics{min-height:calc(100vh - 54px);background:var(--bg)}
.an-wrap{padding:20px 24px 48px}
.an-hero{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.an-title{font-size:18px;font-weight:700;color:var(--txt);letter-spacing:-.4px}
.an-meta{font-size:12px;color:var(--txt3);margin-top:3px}
.an-meta strong{color:var(--txt2);font-weight:600}
.an-charts-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.an-card{background:var(--surface);border-radius:var(--r);box-shadow:var(--sh);padding:16px 20px;border:1px solid var(--border-lite)}
.an-card-title{font-size:12px;font-weight:700;color:var(--txt);letter-spacing:-.1px}
.an-card-sub{font-size:11px;color:var(--txt3);margin-top:2px;margin-bottom:12px}
.an-chart{width:100%;height:260px}
.an-table-card{background:var(--surface);border-radius:var(--r);box-shadow:var(--sh);margin-bottom:14px;overflow:hidden;border:1px solid var(--border-lite)}
.an-table-head{padding:14px 20px 12px;border-bottom:1px solid var(--border-lite)}
.an-table-title{font-size:13px;font-weight:700;color:var(--txt)}
.an-table-sub{font-size:11px;color:var(--txt3);margin-top:2px}
.an-table-card table.dataTable thead th{background:var(--bg);color:var(--txt3);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;padding:10px 14px!important;border-bottom:1px solid var(--border)!important;white-space:nowrap}
.an-table-card table.dataTable tbody td{padding:9px 14px!important;font-size:13px;border-bottom:1px solid var(--border-lite)!important;color:var(--txt)}
.an-table-card table.dataTable tbody tr:hover td{background:var(--accent-bg)!important}
.diff-up{color:var(--success);font-weight:600}
.diff-dn{color:var(--danger);font-weight:600}
.ins-legend{background:var(--surface);border:1px solid var(--border-lite);border-radius:var(--r);padding:12px 16px;margin-bottom:16px;font-size:12px;color:var(--txt2);line-height:2}
.ins-sig{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.ins-buy{background:#ECFDF5;color:#059669}
.ins-neutral{background:#FFFBEB;color:#D97706}
.ins-above{background:#FEF2F2;color:#DC2626}
/* ── Upload button & toast ── */
.btn-upload{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);border-radius:6px;padding:6px 13px;font-size:12px;font-weight:500;cursor:pointer;color:rgba(255,255,255,.75);font-family:inherit;transition:all .15s;white-space:nowrap;user-select:none;letter-spacing:-.1px}
.btn-upload:hover{background:rgba(212,118,26,.25);border-color:var(--accent);color:#fff}
.btn-upload svg{flex-shrink:0}
.upload-toast{position:fixed;bottom:24px;right:24px;z-index:9999;pointer-events:none}
.upload-toast-inner{background:var(--nav);color:#fff;border-radius:10px;padding:12px 18px;display:flex;align-items:center;gap:10px;font-size:13px;font-weight:500;box-shadow:0 8px 24px rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.08);animation:toastIn .2s ease}
@keyframes toastIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.upload-toast-icon{font-size:15px}
/* Upload drop-zone overlay */
.upload-overlay{display:none;position:fixed;inset:0;background:rgba(26,23,20,.6);z-index:8000;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.upload-overlay.show{display:flex}
.upload-box{background:var(--surface);border-radius:16px;padding:48px 56px;text-align:center;border:2px dashed var(--border);transition:border-color .2s;max-width:420px;width:90%}
.upload-box.drag-over{border-color:var(--accent);background:var(--accent-bg)}
.upload-box-icon{font-size:40px;margin-bottom:16px}
.upload-box-title{font-size:17px;font-weight:700;color:var(--txt);margin-bottom:6px;letter-spacing:-.3px}
.upload-box-sub{font-size:13px;color:var(--txt3);margin-bottom:24px;line-height:1.5}
.upload-btn-primary{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 22px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:background .15s}
.upload-btn-primary:hover{background:var(--accent-h)}
.upload-cancel{display:block;margin-top:14px;font-size:12px;color:var(--txt3);cursor:pointer;background:none;border:none;font-family:inherit}
.upload-cancel:hover{color:var(--danger)}

/* ── Listings Page ── */
#page-listings{min-height:calc(100vh - 54px);background:var(--bg)}
.ls-wrap{padding:20px 24px 48px}
.ls-hero{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.ls-title{font-size:18px;font-weight:700;color:var(--txt);letter-spacing:-.4px}
.ls-meta{font-size:12px;color:var(--txt3);margin-top:3px}
.ls-meta strong{color:var(--txt2);font-weight:600}
.ls-kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.ls-filter-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px;padding:12px 16px;background:var(--surface);border-radius:var(--r);border:1px solid var(--border-lite);box-shadow:var(--sh)}
.ls-filter-label{font-size:10px;font-weight:600;color:var(--txt3);text-transform:uppercase;letter-spacing:.6px;white-space:nowrap}
.ls-pills{display:flex;gap:5px;flex-wrap:wrap}
.ls-pill{padding:4px 11px;border-radius:999px;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);background:var(--bg);color:var(--txt2);transition:all .14s;white-space:nowrap;font-family:inherit}
.ls-pill:hover{border-color:var(--accent);color:var(--accent)}
.ls-pill.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.ls-sep{width:1px;height:24px;background:var(--border);flex-shrink:0}
.ls-view-toggle{display:flex;gap:5px;margin-left:auto}
.ls-view-btn{padding:4px 12px;border-radius:var(--r-sm);font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);background:var(--bg);color:var(--txt2);transition:all .14s;font-family:inherit}
.ls-view-btn.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.ls-table-card{background:var(--surface);border-radius:var(--r);box-shadow:var(--sh);margin-bottom:14px;overflow:hidden;border:1px solid var(--border-lite)}
.ls-table-head{padding:14px 20px 12px;border-bottom:1px solid var(--border-lite);display:flex;align-items:center;justify-content:space-between}
.ls-table-title{font-size:13px;font-weight:700;color:var(--txt)}
.ls-table-sub{font-size:11px;color:var(--txt3);margin-top:2px}
.ls-table-card table.dataTable thead th{background:var(--bg);color:var(--txt3);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;padding:10px 14px!important;border-bottom:1px solid var(--border)!important;white-space:nowrap}
.ls-table-card table.dataTable tbody td{padding:9px 14px!important;font-size:13px;border-bottom:1px solid var(--border-lite)!important;color:var(--txt)}
.ls-table-card table.dataTable tbody tr:hover td{background:var(--accent-bg)!important}
.ls-empty{text-align:center;padding:64px 24px;color:var(--txt3)}
.ls-empty-icon{font-size:40px;margin-bottom:12px}
.ls-empty-title{font-size:15px;font-weight:600;color:var(--txt2);margin-bottom:6px}
.ls-empty-sub{font-size:13px;line-height:1.5}
.ls-link{color:var(--accent);text-decoration:none;font-size:12px}
.ls-link:hover{text-decoration:underline}
.snap-badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:500;padding:3px 9px;border-radius:999px;border:1px solid}
.snap-badge.ok{color:var(--success);background:#ECFDF5;border-color:rgba(21,128,61,.2)}
.snap-badge.due{color:var(--danger);background:#FEF2F2;border-color:rgba(220,38,38,.2)}
.btn-scrape{display:inline-flex;align-items:center;gap:6px;background:var(--accent);border:none;border-radius:var(--r-sm);padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;color:#fff;font-family:inherit;transition:all .15s;white-space:nowrap}
.btn-scrape:hover:not(:disabled){background:#1d4ed8}
.btn-scrape:disabled{opacity:.55;cursor:not-allowed}
.btn-scrape.running{background:#6366f1}
.btn-scrape.success{background:var(--success)}
.btn-scrape.error{background:var(--danger)}
.ls-trends-chart-wrap{padding:14px 20px 0}
.ls-trend-note{text-align:center;padding:14px 20px;font-size:12px;color:var(--txt3);background:var(--accent-bg);border-radius:var(--r-sm);margin:12px 20px 0;border:1px solid rgba(212,118,26,.12)}
.ls-trends-card-table{padding:0;margin-top:4px}
.ls-trends-card-table table.dataTable thead th{background:var(--bg);color:var(--txt3);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;padding:10px 14px!important;border-bottom:1px solid var(--border)!important;white-space:nowrap}
.ls-trends-card-table table.dataTable tbody td{padding:9px 14px!important;font-size:13px;border-bottom:1px solid var(--border-lite)!important;color:var(--txt)}
.ls-trends-card-table table.dataTable tbody tr:hover td{background:var(--accent-bg)!important}

</style>
</head>
<body>

<!-- NAVBAR -->
<nav class="navbar">
  <div class="brand"><div class="brand-mark">AD</div>Abu Dhabi RE Intelligence</div>
  <div class="nav-tabs">
    <a class="nav-tab active" id="tab-explorer" onclick="switchPage('explorer')">Data Explorer</a>
    <a class="nav-tab" id="tab-listings" onclick="switchPage('listings')">PF Listings</a>
    <a class="nav-tab" id="tab-analytics" onclick="switchPage('analytics')">Analytics</a>
    <a class="nav-tab" id="tab-insights" onclick="switchPage('insights')">Insights</a>
  </div>
  <div class="nav-spacer"></div>
  <button class="btn-upload" onclick="openUploadOverlay()" title="Upload new CSV export from ADREC">
    <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10 14V4M5 8l5-5 5 5"/><path d="M3 17h14"/></svg>
    Upload CSV
  </button>
  <span class="nav-badge" id="tx-count">__TX_COUNT__</span>
</nav>
<!-- Upload toast -->
<div id="upload-toast" class="upload-toast" style="display:none">
  <div class="upload-toast-inner">
    <span id="upload-toast-icon">⏳</span>
    <span id="upload-toast-msg">Parsing…</span>
  </div>
</div>

<!-- Upload overlay -->
<div class="upload-overlay" id="upload-overlay" onclick="closeUploadOverlay(event)">
  <div class="upload-box" id="upload-box">
    <div class="upload-box-icon">📂</div>
    <div class="upload-box-title">Upload new data</div>
    <div class="upload-box-sub">Export the CSV from ADREC and drop it here,<br/>or click to browse. The page refreshes instantly.</div>
    <label class="upload-btn-primary">
      <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10 14V4M5 8l5-5 5 5"/><path d="M3 17h14"/></svg>
      Choose CSV file
      <input type="file" accept=".csv" style="display:none" onchange="handleCSVUpload(event)"/>
    </label>
    <button class="upload-cancel" onclick="closeUploadOverlay()">Cancel</button>
  </div>
</div>

<!-- PAGE 1: DATA EXPLORER -->
<div class="page active" id="page-explorer">
  <div class="explorer-layout">

    <!-- SIDEBAR -->
    <aside class="sidebar">
      <div class="sb-head">
        <div class="sb-title">
          <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="3" y1="6" x2="17" y2="6"/><line x1="6" y1="10" x2="14" y2="10"/><line x1="9" y1="14" x2="11" y2="14"/></svg>
          Filters
        </div>
        <button class="sb-clear" onclick="resetFilters()">Reset all</button>
      </div>

      <!-- Global search -->
      <div class="sb-search-wrap">
        <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="9" cy="9" r="6"/><path d="M15 15l3 3"/></svg>
        <input class="sb-search" id="search-box" type="text" placeholder="Search project, community…" oninput="applyFilters()"/>
      </div>

      <!-- Date Range -->
      <div class="fs open" id="fs-date">
        <div class="fs-head" onclick="toggleFs('fs-date')">
          <div class="fs-head-left">
            <span class="fs-title">Date Range</span>
            <span class="fs-badge" id="fs-date-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="sb-dates">
            <div class="sb-date-group">
              <div class="sb-date-lbl">From</div>
              <input class="sb-date-in" id="date-from" type="date" onchange="applyFilters()"/>
            </div>
            <div class="sb-date-group">
              <div class="sb-date-lbl">To</div>
              <input class="sb-date-in" id="date-to" type="date" onchange="applyFilters()"/>
            </div>
          </div>
        </div>
      </div>

      <!-- Property Type -->
      <div class="fs open" id="fs-type">
        <div class="fs-head" onclick="toggleFs('fs-type')">
          <div class="fs-head-left">
            <span class="fs-title">Property Type</span>
            <span class="fs-badge" id="fs-type-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="clSelectAll('type')">All</button>
            <button class="cl-act dim" onclick="clClear('type')">Clear</button>
          </div>
          <div class="cl-list" id="cl-type"></div>
        </div>
      </div>

      <!-- Sale Type -->
      <div class="fs open" id="fs-saletype">
        <div class="fs-head" onclick="toggleFs('fs-saletype')">
          <div class="fs-head-left">
            <span class="fs-title">Sale Type</span>
            <span class="fs-badge" id="fs-saletype-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="clSelectAll('saletype')">All</button>
            <button class="cl-act dim" onclick="clClear('saletype')">Clear</button>
          </div>
          <div class="cl-list" id="cl-saletype"></div>
        </div>
      </div>

      <!-- Bedrooms -->
      <div class="fs open" id="fs-layout">
        <div class="fs-head" onclick="toggleFs('fs-layout')">
          <div class="fs-head-left">
            <span class="fs-title">Bedrooms</span>
            <span class="fs-badge" id="fs-layout-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="clSelectAll('layout')">All</button>
            <button class="cl-act dim" onclick="clClear('layout')">Clear</button>
          </div>
          <div class="cl-list" id="cl-layout"></div>
        </div>
      </div>

      <!-- District -->
      <div class="fs open" id="fs-district">
        <div class="fs-head" onclick="toggleFs('fs-district')">
          <div class="fs-head-left">
            <span class="fs-title">District</span>
            <span class="fs-badge" id="fs-district-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="clSelectAll('district')">All</button>
            <button class="cl-act dim" onclick="clClear('district')">Clear</button>
          </div>
          <input class="cl-search" type="text" placeholder="Search districts…" oninput="filterDistrictList(this.value)"/>
          <div class="cl-list" id="cl-district"></div>
        </div>
      </div>
    </aside>

    <!-- MAIN CONTENT -->
    <div class="main-content">

      <!-- KPI Strip -->
      <div class="kpi-strip">
        <div class="kpi-tile">
          <div class="kpi-icon blue">📊</div>
          <div>
            <div class="kpi-val" id="kpi-tx">—</div>
            <div class="kpi-lbl">Transactions</div>
          </div>
        </div>
        <div class="kpi-tile">
          <div class="kpi-icon green">💰</div>
          <div>
            <div class="kpi-val" id="kpi-price">—</div>
            <div class="kpi-lbl">Median Price (AED)</div>
          </div>
        </div>
        <div class="kpi-tile">
          <div class="kpi-icon amber">📐</div>
          <div>
            <div class="kpi-val" id="kpi-rate">—</div>
            <div class="kpi-lbl">Median AED/SQM</div>
          </div>
        </div>
        <div class="kpi-tile">
          <div class="kpi-icon violet">🏗️</div>
          <div>
            <div class="kpi-val" id="kpi-offplan">—</div>
            <div class="kpi-lbl">Off-Plan Share</div>
          </div>
        </div>
      </div>

      <!-- Table area -->
      <div class="table-area">
        <div class="table-toolbar">
          <div class="table-info">
            <strong id="kpi-tx-small">—</strong>
            <span>transactions</span>
            <span class="result-badge" id="filter-badge" style="display:none"></span>
          </div>
          <button class="btn-export" onclick="exportCSV()">
            <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 3v10M5 13l5 5 5-5"/><path d="M3 17h14"/></svg>
            Export CSV
          </button>
        </div>
        <div class="card">
          <table id="main-table" class="display" style="width:100%">
            <thead>
              <tr>
                <th>Date</th><th>District</th><th>Community</th><th>Project</th>
                <th>Type</th><th>Layout</th><th>Price (AED)</th><th>Area (SQM)</th>
                <th>Rate/SQM</th><th>Sale Type</th>
              </tr>
            </thead>
            <tbody id="table-body"></tbody>
          </table>
        </div>
      </div>

    </div>
  </div>
</div>

<!-- PAGE 2: ANALYTICS -->
<div class="page" id="page-analytics">
  <div class="an-wrap">

    <div class="an-hero">
      <div>
        <div class="an-title">Market Analytics</div>
        <div class="an-meta">Analyzing <strong id="an-count">—</strong> transactions · based on current filter selection</div>
      </div>
    </div>

    <!-- Charts row -->
    <div class="an-charts-row">
      <div class="an-card">
        <div class="an-card-title">Price Distribution</div>
        <div class="an-card-sub">Transaction count by price band — one line per year</div>
        <div class="an-chart" id="an-chart-dist"></div>
      </div>
      <div class="an-card">
        <div class="an-card-title">Average Rate Over Time</div>
        <div class="an-card-sub">Annual average AED per sq ft</div>
        <div class="an-chart" id="an-chart-trend"></div>
      </div>
    </div>

    <!-- Project summary table -->
    <div class="an-table-card">
      <div class="an-table-head">
        <div class="an-table-title">Project Summary</div>
        <div class="an-table-sub">Average &amp; range of sale prices — per project · layout · type</div>
      </div>
      <table id="an-proj-table" class="display" style="width:100%">
        <thead>
          <tr>
            <th>Project</th><th>Type</th><th>Layout</th><th>Transactions</th>
            <th>Avg Price (AED)</th><th>Min Price</th><th>Max Price</th><th>Avg AED/sqft</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- Off-plan vs ready comparison table -->
    <div class="an-table-card">
      <div class="an-table-head">
        <div class="an-table-title">Off-Plan vs Ready — Price Comparison</div>
        <div class="an-table-sub">Average sale price (AED) for same project &amp; layout — off-plan vs ready</div>
      </div>
      <table id="an-cmp-table" class="display" style="width:100%">
        <thead>
          <tr>
            <th>Project</th><th>Layout</th>
            <th>Off-Plan Avg (AED)</th><th>Ready Avg (AED)</th>
            <th>Diff</th><th>Off-Plan Txns</th><th>Ready Txns</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>

  </div>
</div>

<!-- PAGE 3: PF LISTINGS -->
<div class="page" id="page-listings">
  <div class="explorer-layout">

    <!-- SIDEBAR FILTERS -->
    <aside class="sidebar">
      <div class="sb-head">
        <div class="sb-title">
          <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="3" y1="6" x2="17" y2="6"/><line x1="6" y1="10" x2="14" y2="10"/><line x1="9" y1="14" x2="11" y2="14"/></svg>
          Filters
        </div>
        <button class="sb-clear" onclick="lsResetFilters()">Reset all</button>
      </div>

      <!-- Property Type -->
      <div class="fs open" id="ls-fs-type">
        <div class="fs-head" onclick="toggleFs('ls-fs-type')">
          <div class="fs-head-left">
            <span class="fs-title">Property Type</span>
            <span class="fs-badge" id="ls-fs-type-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="lsClSelectAll('type')">All</button>
            <button class="cl-act dim" onclick="lsClClear('type')">Clear</button>
          </div>
          <div class="cl-list" id="ls-cl-type"></div>
        </div>
      </div>

      <!-- Sale Type -->
      <div class="fs open" id="ls-fs-saletype">
        <div class="fs-head" onclick="toggleFs('ls-fs-saletype')">
          <div class="fs-head-left">
            <span class="fs-title">Sale Type</span>
            <span class="fs-badge" id="ls-fs-saletype-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="lsClSelectAll('saletype')">All</button>
            <button class="cl-act dim" onclick="lsClClear('saletype')">Clear</button>
          </div>
          <div class="cl-list" id="ls-cl-saletype"></div>
        </div>
      </div>

      <!-- Bedrooms -->
      <div class="fs open" id="ls-fs-beds">
        <div class="fs-head" onclick="toggleFs('ls-fs-beds')">
          <div class="fs-head-left">
            <span class="fs-title">Bedrooms</span>
            <span class="fs-badge" id="ls-fs-beds-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="lsClSelectAll('beds')">All</button>
            <button class="cl-act dim" onclick="lsClClear('beds')">Clear</button>
          </div>
          <div class="cl-list" id="ls-cl-beds"></div>
        </div>
      </div>

      <!-- District -->
      <div class="fs open" id="ls-fs-district">
        <div class="fs-head" onclick="toggleFs('ls-fs-district')">
          <div class="fs-head-left">
            <span class="fs-title">District</span>
            <span class="fs-badge" id="ls-fs-district-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="lsClSelectAll('district')">All</button>
            <button class="cl-act dim" onclick="lsClClear('district')">Clear</button>
          </div>
          <input class="cl-search" type="text" placeholder="Search districts…" oninput="lsFilterDistrictList(this.value)"/>
          <div class="cl-list" id="ls-cl-district"></div>
        </div>
      </div>

      <!-- Listed Month -->
      <div class="fs open" id="ls-fs-month">
        <div class="fs-head" onclick="toggleFs('ls-fs-month')">
          <div class="fs-head-left">
            <span class="fs-title">Listed Month</span>
            <span class="fs-badge" id="ls-fs-month-badge" style="display:none"></span>
          </div>
          <span class="fs-chevron">▼</span>
        </div>
        <div class="fs-body">
          <div class="cl-acts">
            <button class="cl-act" onclick="lsClSelectAll('month')">All</button>
            <button class="cl-act dim" onclick="lsClClear('month')">Clear</button>
          </div>
          <div class="cl-list" id="ls-cl-month"></div>
        </div>
      </div>
    </aside>

    <!-- MAIN CONTENT -->
    <div class="main-content">
      <div class="ls-wrap">

        <div class="ls-hero">
          <div>
            <div class="ls-title">Property Finder — Abu Dhabi Listings</div>
            <div class="ls-meta">Live listings · <strong id="ls-count">—</strong> records · scraped from propertyfinder.ae</div>
            <div id="ls-snap-status" style="margin-top:6px"></div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
            <div class="ls-view-toggle">
              <button class="ls-view-btn on" id="ls-btn-summary" onclick="lsSetView('summary')">Summary</button>
              <button class="ls-view-btn" id="ls-btn-full" onclick="lsSetView('full')">All Listings</button>
              <button class="ls-view-btn" id="ls-btn-trends" onclick="lsSetView('trends')">Price Trends</button>
            </div>
            <button class="btn-export" onclick="exportPFCSV()">
              <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 3v10M5 13l5 5 5-5"/><path d="M3 17h14"/></svg>
              Export CSV
            </button>
            <button class="btn-scrape" id="btn-scrape" onclick="runScraper()">
              <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4 4v5h5"/><path d="M16 16v-5h-5"/><path d="M4.93 9A8 8 0 1 1 4 12"/></svg>
              Refresh PF Data
            </button>
          </div>
        </div>

        <!-- KPI row -->
        <div class="ls-kpi-row">
          <div class="kpi-tile"><div class="kpi-icon blue">🏢</div><div><div class="kpi-val" id="ls-kpi-n">—</div><div class="kpi-lbl">Listings</div></div></div>
          <div class="kpi-tile"><div class="kpi-icon green">💰</div><div><div class="kpi-val" id="ls-kpi-avg">—</div><div class="kpi-lbl">Avg Price (AED)</div></div></div>
          <div class="kpi-tile"><div class="kpi-icon amber">📐</div><div><div class="kpi-val" id="ls-kpi-sqft">—</div><div class="kpi-lbl">Avg AED/sqft</div></div></div>
          <div class="kpi-tile"><div class="kpi-icon violet">🛏️</div><div><div class="kpi-val" id="ls-kpi-types">—</div><div class="kpi-lbl">Property Types</div></div></div>
        </div>

        <!-- Summary table -->
        <div class="ls-table-card" id="ls-summary-card">
          <div class="ls-table-head">
            <div>
              <div class="ls-table-title">Summary by Area · Type · Bedrooms</div>
              <div class="ls-table-sub">Average, min &amp; max prices — grouped by location, property type and bedroom count</div>
            </div>
          </div>
          <table id="ls-summary-table" class="display" style="width:100%">
            <thead><tr>
              <th>Area / District</th><th>Type</th><th>Bedrooms</th><th>Listings</th>
              <th>Avg Price (AED)</th><th>Min Price</th><th>Max Price</th><th>Avg AED/sqft</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>

        <!-- Full listings table -->
        <div class="ls-table-card" id="ls-full-card" style="display:none">
          <div class="ls-table-head">
            <div>
              <div class="ls-table-title">All Listings</div>
              <div class="ls-table-sub">Individual property listings from propertyfinder.ae</div>
            </div>
          </div>
          <table id="ls-full-table" class="display" style="width:100%">
            <thead><tr>
              <th>Title</th><th>Community</th><th>Type</th><th>Beds</th><th>District</th>
              <th>Sale Type</th><th>Price (AED)</th><th>Area (sqft)</th><th>AED/sqft</th><th>Link</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>

        <!-- Price Trends card -->
        <div class="ls-table-card" id="ls-trends-card" style="display:none">
          <div class="ls-table-head">
            <div>
              <div class="ls-table-title">Price Trends</div>
              <div class="ls-table-sub" id="ls-trends-meta">—</div>
            </div>
          </div>
          <div class="ls-trends-chart-wrap">
            <div id="ls-trends-chart" style="width:100%;height:320px"></div>
            <div id="ls-trends-note" class="ls-trend-note" style="display:none">
              📅 Only one snapshot collected so far. Trend lines will appear once a second monthly snapshot is saved.
            </div>
          </div>
          <div class="ls-trends-card-table">
            <table id="ls-trend-table" class="display" style="width:100%">
              <thead><tr>
                <th>Area</th><th>Type</th><th>Beds</th><th>Months Tracked</th>
                <th>First Avg (AED)</th><th>Latest Avg (AED)</th><th>Δ AED</th><th>Δ %</th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
        </div>

        <!-- Empty state -->
        <div id="ls-empty" style="display:none">
          <div class="ls-empty">
            <div class="ls-empty-icon">🔍</div>
            <div class="ls-empty-title">No listings available</div>
            <div class="ls-empty-sub">Property Finder data could not be fetched at build time.<br/>Re-run <code>python3 build_mashvisor.py</code> with an internet connection<br/>and the <code>requests</code> library installed (<code>pip install requests</code>).</div>
          </div>
        </div>

      </div>
    </div>

  </div>
</div>

<!-- PAGE 4: INSIGHTS -->
<div class="page" id="page-insights">
  <div class="an-wrap">

    <div class="an-hero">
      <div>
        <div class="an-title">Market Insights</div>
        <div class="an-meta">Demand vs supply — <strong id="ins-tx-count">—</strong> historical transactions vs <strong id="ins-pf-count">—</strong> active PF listings · grouped by community + type + bedrooms</div>
      </div>
    </div>

    <!-- Legend -->
    <div class="ins-legend">
      <strong>Signal logic (per community · type · bedrooms):</strong>
      &nbsp;<span class="ins-sig ins-buy">Buy Signal</span> ask price below or near historical sale avg and/or prices softening
      &nbsp;·&nbsp;<span class="ins-sig ins-neutral">Neutral</span> at market level
      &nbsp;·&nbsp;<span class="ins-sig ins-above">Above Market</span> asking above historical with no downward trend
      <br><span style="font-size:11px;color:var(--txt3)">
        <strong>Ask vs Sale</strong> — green (+%) = asking BELOW historical avg (good deal) · red (−%) = above historical &nbsp;|&nbsp;
        <strong>6M Trend</strong> — green (−%) = prices falling (softening market) · red (+%) = rising &nbsp;|&nbsp;
        <strong>Neg. Gap</strong> — how far ask is above historical avg; large = more room to negotiate · negative = already below market
      </span>
    </div>

    <!-- Top 10 -->
    <div class="an-table-card">
      <div class="an-table-head">
        <div class="an-table-title">Top 10 Most Attractive for Buyers</div>
        <div class="an-table-sub">Current PF listings ranked by ask price vs historical sale, price trend, and negotiation gap</div>
      </div>
      <table id="ins-top10-table" class="display" style="width:100%">
        <thead><tr>
          <th>#</th><th>Community</th><th>Type</th><th>Beds</th><th>District</th>
          <th>PF Ads</th><th>Ask AED/sqm</th><th>Hist. Sale AED/sqm</th>
          <th>Ask vs Sale</th><th>6M Trend</th><th>Neg. Gap</th><th>Signal</th><th></th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- Full analysis -->
    <div class="an-table-card">
      <div class="an-table-head">
        <div class="an-table-title">Full Analysis — All Communities with Active Listings</div>
        <div class="an-table-sub">All community · type · bedroom groups with both active PF listings and sufficient transaction history (≥5 txns)</div>
      </div>
      <table id="ins-full-table" class="display" style="width:100%">
        <thead><tr>
          <th>Community</th><th>Type</th><th>Beds</th><th>District</th>
          <th>PF Ads</th><th>Hist. Txns</th><th>Ask AED/sqm</th><th>Hist. Sale AED/sqm</th>
          <th>Ask vs Sale</th><th>6M Trend</th><th>Neg. Gap</th><th>Signal</th><th></th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>

  </div>
</div>

<!-- SCRIPTS -->
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/2.0.3/js/dataTables.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/papaparse@5.4.1/papaparse.min.js"></script>

<script>
// ── Embedded Data ────────────────────────────────────────────────────────────
let TABLE_DATA = __TABLE_DATA__;
const PF_DATA = __PF_DATA__;
const PF_TREND_DATA   = __PF_TREND_DATA__;
const PF_SNAP_MONTH   = '__PF_SNAP_MONTH__';

// ── Page Switching ────────────────────────────────────────────────────────────
function switchPage(page){
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  document.getElementById('tab-'+page).classList.add('active');
  if(page === 'analytics') renderAnalytics();
  if(page === 'listings'){ renderListings(); renderSnapStatus(); }
  if(page === 'insights') renderInsights();
}

// ── Filter State ──────────────────────────────────────────────────────────────
const filterState = { type: new Set(), district: new Set(), layout: new Set(), saletype: new Set() };
let dtTable = null;
let _currentFiltered = null;

function fmtNum(n){ return n == null ? '—' : n.toLocaleString(); }
function fmtDate(s){ return s || ''; }

// Derive value lists — recomputed after upload via initLookups()
let allTypes = [], allLayouts = [], allSaleTypes = [], allDistricts = [];
let minDate = '', maxDate = '';
let COUNTS = {};

function computeCounts(items, key){
  const counts = {};
  items.forEach(v => { counts[v] = 0; });
  TABLE_DATA.forEach(r => { if(r[key] && counts[r[key]] !== undefined) counts[r[key]]++; });
  return counts;
}

function initLookups(){
  allTypes     = [...new Set(TABLE_DATA.map(r=>r.ty))].filter(Boolean).sort();
  allLayouts   = [...new Set(TABLE_DATA.map(r=>r.la))].filter(Boolean).sort();
  allSaleTypes = [...new Set(TABLE_DATA.map(r=>r.st))].filter(Boolean).sort();
  allDistricts = [...new Set(TABLE_DATA.map(r=>r.di))].filter(Boolean).sort();
  const allDates = TABLE_DATA.map(r=>r.d).filter(Boolean).sort();
  minDate = allDates[0] || '';
  maxDate = allDates[allDates.length-1] || '';
  COUNTS = {
    type:     computeCounts(allTypes,     'ty'),
    layout:   computeCounts(allLayouts,   'la'),
    saletype: computeCounts(allSaleTypes, 'st'),
    district: computeCounts(allDistricts, 'di'),
  };
}

// ── Sidebar accordion ─────────────────────────────────────────────────────────
function toggleFs(id){
  document.getElementById(id).classList.toggle('open');
}

// ── Checklist builder ─────────────────────────────────────────────────────────
function buildChecklist(containerId, items, dimension){
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  items.forEach(val => {
    const isOn = filterState[dimension].has(val);
    const item = document.createElement('label');
    item.className = 'cl-item' + (isOn ? ' on' : '');
    item.innerHTML = `<input type="checkbox" ${isOn?'checked':''}><span class="cl-item-label">${val}</span><span class="cl-item-count">${(COUNTS[dimension][val]||0).toLocaleString()}</span>`;
    item.querySelector('input').addEventListener('change', e => {
      if(e.target.checked) filterState[dimension].add(val);
      else filterState[dimension].delete(val);
      item.classList.toggle('on', e.target.checked);
      updateFsBadge(dimension);
      applyFilters();
    });
    container.appendChild(item);
  });
}

function updateFsBadge(dimension){
  const ids = { type:'fs-type-badge', layout:'fs-layout-badge', saletype:'fs-saletype-badge', district:'fs-district-badge' };
  const badge = document.getElementById(ids[dimension]);
  if(!badge) return;
  const n = filterState[dimension].size;
  badge.textContent = n;
  badge.style.display = n > 0 ? '' : 'none';
}

function clSelectAll(dimension){
  const items = dimension==='type'?allTypes:dimension==='layout'?allLayouts:dimension==='saletype'?allSaleTypes:allDistricts;
  items.forEach(v => filterState[dimension].add(v));
  buildChecklist('cl-'+dimension, items, dimension);
  updateFsBadge(dimension);
  applyFilters();
}

function clClear(dimension){
  filterState[dimension].clear();
  const items = dimension==='type'?allTypes:dimension==='layout'?allLayouts:dimension==='saletype'?allSaleTypes:allDistricts;
  buildChecklist('cl-'+dimension, items, dimension);
  updateFsBadge(dimension);
  applyFilters();
}

function filterDistrictList(query){
  const q = query.toLowerCase().trim();
  const items = q ? allDistricts.filter(d => d.toLowerCase().includes(q)) : allDistricts;
  buildChecklist('cl-district', items, 'district');
}

// ── KPI strip ─────────────────────────────────────────────────────────────────
function updateKPIs(filtered){
  const n = filtered.length;
  const prices = filtered.map(r=>r.p).filter(v=>v!=null).sort((a,b)=>a-b);
  const rates  = filtered.map(r=>r.r).filter(v=>v!=null).sort((a,b)=>a-b);
  const offPlan = filtered.filter(r=>r.st==='off-plan').length;
  const med = arr => arr.length ? arr[Math.floor(arr.length/2)] : null;
  const fmtM = v => v==null?'—':v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e3?(v/1e3).toFixed(0)+'K':v.toLocaleString();
  document.getElementById('kpi-tx').textContent      = n.toLocaleString();
  document.getElementById('kpi-tx-small').textContent = n.toLocaleString();
  document.getElementById('kpi-price').textContent   = fmtM(med(prices));
  document.getElementById('kpi-rate').textContent    = med(rates) ? med(rates).toLocaleString() : '—';
  document.getElementById('kpi-offplan').textContent = n>0 ? (offPlan/n*100).toFixed(1)+'%' : '—';
  const badge = document.getElementById('filter-badge');
  if(n < TABLE_DATA.length){ badge.textContent=`filtered from ${TABLE_DATA.length.toLocaleString()}`; badge.style.display=''; }
  else { badge.style.display='none'; }
}

// ── Export CSV ────────────────────────────────────────────────────────────────
function exportCSV(){
  const headers = ['Date','District','Community','Project','Type','Layout','Price (AED)','Area (SQM)','Rate/SQM','Sale Type'];
  const rows = _currentFiltered || TABLE_DATA;
  const lines = [headers.join(',')];
  rows.forEach(r => {
    lines.push([r.d,r.di,r.co,`"${(r.pr||'').replace(/"/g,'""')}"`,r.ty,r.la,r.p||'',r.a||'',r.r||'',r.st].join(','));
  });
  const blob = new Blob([lines.join('\n')], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'abu_dhabi_transactions.csv';
  a.click();
}

// Stub (was used for old dropdown panels, kept for safety)
function closeAllDropdowns(){}

// ── Table rendering ───────────────────────────────────────────────────────────
function buildTableRows(data){
  return data.map(r => [
    fmtDate(r.d),
    r.di || '',
    r.co || '',
    r.pr || '',
    r.ty || '',
    r.la || '',
    r.p  != null ? r.p.toLocaleString() : '—',
    r.a  != null ? r.a.toLocaleString() : '—',
    r.r  != null ? r.r.toLocaleString() : '—',
    r.st || '',
  ]);
}

function renderSaleTypeBadge(cell, cellData){
  if(cellData === 'off-plan') cell.innerHTML = '<span class="badge badge-offplan">Off-Plan</span>';
  else if(cellData === 'ready') cell.innerHTML = '<span class="badge badge-ready">Ready</span>';
}

function initTableWith(data){
  if(dtTable){ dtTable.destroy(); dtTable = null; }
  $('#main-table tbody').empty();
  dtTable = $('#main-table').DataTable({
    data: buildTableRows(data),
    pageLength: 50,
    lengthMenu: [25, 50, 100, 250],
    order: [[0, 'desc']],
    dom: '<"dt-top"l>rt<"dt-foot"ip>',
    language: _dtLang,
    columnDefs: [
      { targets: 9, createdCell: (cell, cellData) => renderSaleTypeBadge(cell, cellData) }
    ],
  });
}

// ── Apply filters ─────────────────────────────────────────────────────────────
function applyFilters(){
  const search    = document.getElementById('search-box').value.toLowerCase().trim();
  const dateFrom  = document.getElementById('date-from').value;
  const dateTo    = document.getElementById('date-to').value;
  const { type, district, layout, saletype } = filterState;

  const typeFilter     = type.size > 0     && type.size < allTypes.length     ? type     : null;
  const districtFilter = district.size > 0 && district.size < allDistricts.length ? district : null;
  const layoutFilter   = layout.size > 0   && layout.size < allLayouts.length   ? layout   : null;
  const saleFilter     = saletype.size > 0 && saletype.size < allSaleTypes.length ? saletype : null;

  const filtered = TABLE_DATA.filter(r => {
    if(search && !`${r.pr} ${r.co} ${r.di}`.toLowerCase().includes(search)) return false;
    if(dateFrom && r.d && r.d < dateFrom) return false;
    if(dateTo   && r.d && r.d > dateTo)   return false;
    if(typeFilter     && !typeFilter.has(r.ty))     return false;
    if(districtFilter && !districtFilter.has(r.di)) return false;
    if(layoutFilter   && !layoutFilter.has(r.la))   return false;
    if(saleFilter     && !saleFilter.has(r.st))     return false;
    return true;
  });

  _currentFiltered = filtered;
  initTableWith(filtered);
  updateKPIs(filtered);
}

// ── Reset all filters ─────────────────────────────────────────────────────────
function resetFilters(){
  document.getElementById('search-box').value = '';
  document.getElementById('date-from').value  = minDate;
  document.getElementById('date-to').value    = maxDate;
  Object.keys(filterState).forEach(k => filterState[k].clear());
  ['type','layout','saletype','district'].forEach(dim => {
    const items = dim==='type'?allTypes:dim==='layout'?allLayouts:dim==='saletype'?allSaleTypes:allDistricts;
    buildChecklist('cl-'+dim, items, dim);
    updateFsBadge(dim);
  });
  _currentFiltered = null;
  initTableWith(TABLE_DATA);
  updateKPIs(TABLE_DATA);
}



// ── Analytics Page ────────────────────────────────────────────────────────────
let _anDtProj = null;
let _anDtCmp  = null;

function renderAnalytics(){
  const data = _currentFiltered || TABLE_DATA;
  document.getElementById('an-count').textContent = data.length.toLocaleString();
  renderAnDistChart(data);
  renderAnTrendChart(data);
  renderAnProjTable(data);
  renderAnCmpTable(data);
}

function renderAnDistChart(data){
  const el = document.getElementById('an-chart-dist');
  let ch = echarts.getInstanceByDom(el);
  if(!ch) ch = echarts.init(el, null, {renderer:'canvas'});
  const bands = [
    [0,         500000,  '< 500K'],
    [500000,   1000000,  '500K\u20131M'],
    [1000000,  1500000,  '1M\u20131.5M'],
    [1500000,  2000000,  '1.5M\u20132M'],
    [2000000,  2500000,  '2M\u20132.5M'],
    [2500000,  3000000,  '2.5M\u20133M'],
    [3000000,  5000000,  '3M\u20135M'],
    [5000000,  Infinity, '5M+'],
  ];
  const bandLabels = bands.map(b=>b[2]);

  // Group by year
  const yearMap = {};
  data.forEach(r => {
    if(r.p==null || !r.d) return;
    const yr = r.d.slice(0,4);
    if(!yearMap[yr]) yearMap[yr] = Array(bands.length).fill(0);
    const bi = bands.findIndex(([lo,hi])=>r.p>=lo&&r.p<hi);
    if(bi>=0) yearMap[yr][bi]++;
  });
  const years = Object.keys(yearMap).sort();

  const palette = [
    '#94a3b8','#64748b','#3b82f6','#6366f1','#8b5cf6',
    '#ec4899','#f97316','#D4761A','#15803D','#0ea5e9'
  ];

  const series = years.map((yr, i) => ({
    name: yr,
    type: 'line',
    data: yearMap[yr],
    smooth: 0.3,
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { color: palette[i % palette.length], width: 2 },
    itemStyle: { color: palette[i % palette.length], borderColor: '#fff', borderWidth: 1.5 },
  }));

  ch.setOption({
    backgroundColor: 'transparent',
    grid: { top: 8, right: 16, bottom: 52, left: 58 },
    legend: {
      data: years, bottom: 0, itemWidth: 16, itemHeight: 3,
      textStyle: { color: '#94a3b8', fontSize: 10 },
      icon: 'roundRect',
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1A1714', borderColor: '#1A1714',
      textStyle: { color: '#fff', fontFamily: 'Inter', fontSize: 12 },
      formatter: params => {
        let html = `<b>${params[0].axisValue}</b>`;
        params.forEach(p => {
          html += `<br/>${p.marker} ${p.seriesName}: <b>${p.value.toLocaleString()}</b> tx`;
        });
        return html;
      }
    },
    xAxis: {
      type: 'category', data: bandLabels,
      axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 10, interval: 0, rotate: 25 }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 }
    },
    series,
  }, true);
  ch.resize();
}

// Count PF listings that match the current Data Explorer filter context
function countMatchingPFListings(){
  if(!PF_DATA || !PF_DATA.length) return null;
  const search    = (document.getElementById('search-box')||{}).value || '';
  const q         = search.toLowerCase().trim();
  const { type: typeF, district: districtF, layout: layoutF, saletype: saleF } = filterState;

  return PF_DATA.filter(r => {
    // Type: "Apartment" / "Villa" / "Townhouse / Attached Villa"  →  PF type string
    if(typeF.size){
      const pt = (r.type||'').toLowerCase();
      const ok = [...typeF].some(t => {
        const tl = t.toLowerCase();
        if(tl.includes('apartment'))  return pt.includes('apartment');
        if(tl.includes('villa') || tl.includes('townhouse')) return pt.includes('villa') || pt.includes('townhouse');
        return pt.includes(tl);
      });
      if(!ok) return false;
    }
    // District: title-case in tx → compare lowercase
    if(districtF.size){
      const pd = (r.district||'').toLowerCase();
      const ok = [...districtF].some(d => {
        const dl = d.toLowerCase();
        return pd.includes(dl) || dl.includes(pd);
      });
      if(!ok) return false;
    }
    // Layout → beds: "2 Bedrooms" → "2 Beds", "Studio" → "Studio", "1 Bedroom" → "1 Bed"
    if(layoutF.size){
      const pb = (r.beds||'').toLowerCase();
      const ok = [...layoutF].some(l => {
        const ll = l.toLowerCase();
        if(ll.includes('studio')) return pb.includes('studio');
        const m = ll.match(/(\d+)/);
        if(!m) return false;
        const n = m[1];
        return pb.startsWith(n + ' bed');
      });
      if(!ok) return false;
    }
    // Sale type
    if(saleF.size){
      const ps = (r.sale_type||'').toLowerCase();
      if(![...saleF].some(s => ps === s.toLowerCase())) return false;
    }
    // Search text → community, title, district
    if(q){
      const haystack = `${r.community||''} ${r.title||''} ${r.district||''}`.toLowerCase();
      if(!haystack.includes(q)) return false;
    }
    return true;
  }).length;
}

function renderAnTrendChart(data){
  const el = document.getElementById('an-chart-trend');
  let ch = echarts.getInstanceByDom(el);
  if(!ch) ch = echarts.init(el, null, {renderer:'canvas'});

  // Aggregate by year: rate average (left axis) + total transaction count (right axis)
  const byYear = {};
  data.forEach(r => {
    if(!r.d) return;
    const yr = r.d.slice(0,4);
    if(!byYear[yr]) byYear[yr] = {sum:0, rn:0, total:0};
    byYear[yr].total++;
    if(r.r != null){ byYear[yr].sum += r.r / 10.764; byYear[yr].rn++; }
  });
  const years  = Object.keys(byYear).sort();
  const avgs   = years.map(y => byYear[y].rn ? Math.round(byYear[y].sum / byYear[y].rn) : null);
  const counts = years.map(y => byYear[y].total);

  // PF matching listings — shown as a single purple dot at the latest year
  const pfCount   = countMatchingPFListings();
  const latestYr  = years[years.length - 1];
  const pfDotData = years.map(y => y === latestYr ? pfCount : null);

  const seriesList = [
    {
      name: 'Avg AED/sqft',
      type: 'line', data: avgs, yAxisIndex: 0,
      smooth: 0.3, symbol:'circle', symbolSize:7,
      lineStyle: {color:'#2563EB', width:2.5},
      itemStyle: {color:'#2563EB', borderColor:'#fff', borderWidth:2},
      areaStyle: {color:{type:'linear',x:0,y:0,x2:0,y2:1,
        colorStops:[{offset:0,color:'rgba(37,99,235,0.18)'},{offset:1,color:'rgba(37,99,235,0)'}]}}
    },
    {
      name: 'Transactions',
      type: 'scatter', data: counts, yAxisIndex: 1,
      symbol: 'circle', symbolSize: 11,
      itemStyle: {color:'#D4761A', borderColor:'#fff', borderWidth:2},
    },
    {
      name: 'PF Listings',
      type: 'scatter', data: pfDotData, yAxisIndex: 1,
      symbol: 'circle', symbolSize: 13,
      itemStyle: {color:'#8B5CF6', borderColor:'#fff', borderWidth:2},
      label: {
        show: true, position: 'top',
        formatter: p => p.value != null ? p.value.toLocaleString() + ' ads' : '',
        fontSize: 10, fontWeight: '600', fontFamily: 'Inter', color: '#8B5CF6',
      },
    },
  ];

  ch.setOption({
    backgroundColor: 'transparent',
    grid: {top:16, right:72, bottom:52, left:72},
    legend: {
      data: ['Avg AED/sqft', 'Transactions', 'PF Listings'],
      bottom: 0, itemWidth: 16, itemHeight: 3,
      textStyle: {color:'#94a3b8', fontSize:10}, icon:'roundRect',
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1A1714', borderColor: '#1A1714',
      textStyle: {color:'#fff', fontFamily:'Inter', fontSize:12},
      formatter: params => {
        let html = `<b>${params[0].axisValue}</b>`;
        params.forEach(p => {
          if(p.value == null) return;
          if(p.seriesName === 'Avg AED/sqft')
            html += `<br/>${p.marker} Avg Rate: <b>${p.value.toLocaleString()} AED/sqft</b>`;
          else if(p.seriesName === 'Transactions')
            html += `<br/>${p.marker} Transactions: <b>${p.value.toLocaleString()}</b>`;
          else
            html += `<br/>${p.marker} PF Listings (current): <b>${p.value.toLocaleString()}</b>`;
        });
        return html;
      }
    },
    xAxis: {
      type: 'category', data: years,
      axisLine: {lineStyle:{color:'#e2e8f0'}}, axisTick:{show:false},
      axisLabel: {color:'#94a3b8', fontSize:11}
    },
    yAxis: [
      {
        type: 'value',
        splitLine: {lineStyle:{color:'#f1f5f9'}},
        axisLabel: {color:'#94a3b8', fontSize:10, formatter: v => v.toLocaleString()},
        axisLine: {show:false},
      },
      {
        type: 'value', position: 'right',
        splitLine: {show:false},
        axisLabel: {color:'#A8A29C', fontSize:10, formatter: v => v>=1000?(v/1000).toFixed(0)+'K':v},
        axisLine: {show:false}, axisTick: {show:false},
      }
    ],
    series: seriesList,
  }, true);
  ch.resize();
}

function renderAnProjTable(data){
  if(_anDtProj){ _anDtProj.destroy(); _anDtProj = null; }
  $('#an-proj-table tbody').empty();
  // Aggregate: group by project + type + layout
  const map = {};
  data.forEach(r => {
    if(!r.pr) return;
    const k = r.pr + '||' + (r.ty||'') + '||' + (r.la||'');
    if(!map[k]) map[k] = {pr:r.pr, ty:r.ty||'—', la:r.la||'—', prices:[], rates:[]};
    if(r.p != null) map[k].prices.push(r.p);
    if(r.r != null) map[k].rates.push(r.r);
  });
  const rows = Object.values(map).map(g => {
    const n    = g.prices.length;
    const avg  = n ? Math.round(g.prices.reduce((a,b)=>a+b,0)/n) : null;
    const mn   = n ? Math.min(...g.prices) : null;
    const mx   = n ? Math.max(...g.prices) : null;
    const rAvg = g.rates.length ? Math.round(g.rates.reduce((a,b)=>a+b,0)/g.rates.length/10.764) : null;
    return [g.pr, g.ty, g.la, n,
      avg  != null ? avg.toLocaleString()  : '—',
      mn   != null ? mn.toLocaleString()   : '—',
      mx   != null ? mx.toLocaleString()   : '—',
      rAvg != null ? rAvg.toLocaleString() : '—'];
  });
  _anDtProj = $('#an-proj-table').DataTable({
    data: rows, pageLength:25, order:[[3,'desc']], dom:'<"dt-top"lf>rt<"dt-foot"ip>',
    language:_dtLang, columnDefs:[{targets:[3,4,5,6,7], className:'dt-right'}]
  });
}

function renderAnCmpTable(data){
  if(_anDtCmp){ _anDtCmp.destroy(); _anDtCmp = null; }
  $('#an-cmp-table tbody').empty();
  // Group by project+layout, separated by sale type
  const op = {}, rd = {};
  data.forEach(r => {
    if(!r.pr || r.p == null) return;
    const k = r.pr + '||' + (r.la||'');
    if(r.st === 'off-plan'){
      if(!op[k]) op[k] = {pr:r.pr, la:r.la||'—', prices:[]};
      op[k].prices.push(r.p);
    } else if(r.st === 'ready'){
      if(!rd[k]) rd[k] = {pr:r.pr, la:r.la||'—', prices:[]};
      rd[k].prices.push(r.p);
    }
  });
  // Only rows present in both
  const keys = Object.keys(op).filter(k => rd[k]);
  const rows = keys.map(k => {
    const opAvg = Math.round(op[k].prices.reduce((a,b)=>a+b,0) / op[k].prices.length);
    const rdAvg = Math.round(rd[k].prices.reduce((a,b)=>a+b,0) / rd[k].prices.length);
    const diff  = rdAvg > 0 ? ((opAvg - rdAvg) / rdAvg * 100).toFixed(1) : null;
    return [op[k].pr, op[k].la,
      opAvg.toLocaleString(), rdAvg.toLocaleString(),
      diff != null ? (parseFloat(diff) >= 0 ? '+' : '') + diff + '%' : '—',
      op[k].prices.length, rd[k].prices.length];
  });
  _anDtCmp = $('#an-cmp-table').DataTable({
    data: rows, pageLength:25, order:[[5,'desc']], dom:'<"dt-top"lf>rt<"dt-foot"ip>',
    language:_dtLang,
    columnDefs:[
      {targets:[2,3,5,6], className:'dt-right'},
      {targets:4, className:'dt-right',
        createdCell:(cell, val) => {
          const v = parseFloat(val);
          if(!isNaN(v)) cell.className += v >= 0 ? ' diff-up' : ' diff-dn';
        }}
    ]
  });
}


// ── Listings Page ────────────────────────────────────────────────────────────
let _lsDtSummary = null;
let _lsDtFull    = null;
let _lsDtTrend   = null;

// Shared DataTables language config
const _dtLang = {
  search: '', searchPlaceholder: 'Search\u2026',
  lengthMenu: '_MENU_ rows',
  paginate: { previous: '\u2190 Prev', next: 'Next \u2192' },
  info: '_START_\u2013_END_ of _TOTAL_ entries',
  infoEmpty: '0 entries', infoFiltered: ' (filtered from _MAX_)',
};
let _lsView      = 'summary';
const _lsFilter  = { type: new Set(), beds: new Set(), district: new Set(), saletype: new Set(), month: new Set() };
let _lsFiltered  = [];
let _lsInitDone  = false;

function renderSnapStatus(){
  const el = document.getElementById('ls-snap-status');
  if(!el) return;
  const now        = new Date();
  const curMonth   = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0');
  const overdue    = !PF_SNAP_MONTH || PF_SNAP_MONTH < curMonth;
  const nextMonth  = new Date(now.getFullYear(), now.getMonth()+1, 1);
  const nextLabel  = nextMonth.toLocaleString('en-US', {month:'short', year:'numeric'});
  if(overdue){
    el.innerHTML = `<span class="snap-badge due">⚠ Snapshot overdue — run <code>python3 build_mashvisor.py</code></span>`;
  } else {
    el.innerHTML = `<span class="snap-badge ok">✓ Up to date · next run due ${nextLabel}</span>`;
  }
}

function renderListings(){
  if(!PF_DATA || !PF_DATA.length){
    document.getElementById('ls-empty').style.display = 'block';
    document.getElementById('ls-summary-card').style.display = 'none';
    document.getElementById('ls-full-card').style.display = 'none';
    document.getElementById('ls-count').textContent = '0';
    ['ls-kpi-n','ls-kpi-avg','ls-kpi-sqft','ls-kpi-types'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    return;
  }
  document.getElementById('ls-empty').style.display = 'none';
  if(!_lsInitDone){
    _lsInitDone = true;
    lsBuildSidebar();
  }
  lsApplyFilter();
}

// Dimension item lists (populated by lsBuildSidebar)
let _lsTypes = [], _lsBeds = [], _lsDistricts = [], _lsSaleTypes = [], _lsMonths = [];

function _fmtMonth(ym){
  const [y, m] = ym.split('-');
  const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return names[parseInt(m,10)-1] + ' ' + y;
}

function lsBuildSidebar(){
  const bedsOrder = ['Studio','1 Bed','2 Beds','3 Beds','4 Beds','5 Beds','Unknown'];
  _lsTypes     = [...new Set(PF_DATA.map(r=>r.type).filter(Boolean))].sort();
  _lsBeds      = bedsOrder.filter(b => PF_DATA.some(r=>r.beds===b));
  _lsDistricts = [...new Set(PF_DATA.map(r=>r.district).filter(Boolean))].sort();
  _lsSaleTypes = [...new Set(PF_DATA.map(r=>r.sale_type).filter(Boolean))].sort();
  _lsMonths    = [...new Set(PF_DATA.map(r=>r.date?r.date.slice(0,7):'').filter(Boolean))].sort().reverse();
  lsBuildChecklist('ls-cl-type',     _lsTypes,     'type');
  lsBuildChecklist('ls-cl-beds',     _lsBeds,      'beds');
  lsBuildChecklist('ls-cl-district', _lsDistricts, 'district');
  lsBuildChecklist('ls-cl-saletype', _lsSaleTypes, 'saletype');
  lsBuildChecklist('ls-cl-month',    _lsMonths,    'month');
}

function lsBuildChecklist(containerId, items, dim){
  const container = document.getElementById(containerId);
  if(!container) return;
  container.innerHTML = '';
  const counts = {};
  PF_DATA.forEach(r => {
    const val = dim==='type' ? r.type
              : dim==='saletype' ? r.sale_type
              : dim==='beds' ? r.beds
              : dim==='month' ? (r.date ? r.date.slice(0,7) : '')
              : r.district;
    if(val) counts[val] = (counts[val]||0) + 1;
  });
  items.forEach(val => {
    const label = dim === 'month' ? _fmtMonth(val) : val;
    const isOn = _lsFilter[dim].has(val);
    const item = document.createElement('label');
    item.className = 'cl-item' + (isOn ? ' on' : '');
    item.innerHTML = `<input type="checkbox" ${isOn?'checked':''}><span class="cl-item-label">${label}</span><span class="cl-item-count">${(counts[val]||0).toLocaleString()}</span>`;
    item.querySelector('input').addEventListener('change', e => {
      if(e.target.checked) _lsFilter[dim].add(val);
      else _lsFilter[dim].delete(val);
      item.classList.toggle('on', e.target.checked);
      lsUpdateFsBadge(dim);
      lsApplyFilter();
    });
    container.appendChild(item);
  });
}

function lsUpdateFsBadge(dim){
  const ids = {type:'ls-fs-type-badge', beds:'ls-fs-beds-badge', saletype:'ls-fs-saletype-badge', district:'ls-fs-district-badge', month:'ls-fs-month-badge'};
  const badge = document.getElementById(ids[dim]);
  if(!badge) return;
  const n = _lsFilter[dim].size;
  badge.textContent = n;
  badge.style.display = n > 0 ? '' : 'none';
}

function _lsItems(dim){ return dim==='type'?_lsTypes:dim==='beds'?_lsBeds:dim==='saletype'?_lsSaleTypes:dim==='month'?_lsMonths:_lsDistricts; }

function lsClSelectAll(dim){
  _lsItems(dim).forEach(v => _lsFilter[dim].add(v));
  lsBuildChecklist('ls-cl-'+dim, _lsItems(dim), dim);
  lsUpdateFsBadge(dim);
  lsApplyFilter();
}

function lsClClear(dim){
  _lsFilter[dim].clear();
  lsBuildChecklist('ls-cl-'+dim, _lsItems(dim), dim);
  lsUpdateFsBadge(dim);
  lsApplyFilter();
}

function lsFilterDistrictList(query){
  const q = query.toLowerCase().trim();
  const items = q ? _lsDistricts.filter(d=>d.toLowerCase().includes(q)) : _lsDistricts;
  lsBuildChecklist('ls-cl-district', items, 'district');
}

function lsResetFilters(){
  Object.keys(_lsFilter).forEach(k => _lsFilter[k].clear());
  ['type','beds','saletype','district','month'].forEach(dim => {
    lsBuildChecklist('ls-cl-'+dim, _lsItems(dim), dim);
    lsUpdateFsBadge(dim);
  });
  lsApplyFilter();
}

function lsApplyFilter(){
  _lsFiltered = PF_DATA.filter(r => {
    if(_lsFilter.type.size     && !_lsFilter.type.has(r.type))                              return false;
    if(_lsFilter.beds.size     && !_lsFilter.beds.has(r.beds))                              return false;
    if(_lsFilter.district.size && !_lsFilter.district.has(r.district))                     return false;
    if(_lsFilter.saletype.size && !_lsFilter.saletype.has(r.sale_type))                    return false;
    if(_lsFilter.month.size    && !_lsFilter.month.has(r.date?r.date.slice(0,7):''))       return false;
    return true;
  });
  document.getElementById('ls-count').textContent = _lsFiltered.length.toLocaleString();
  lsUpdateKPIs();
  if(_lsView === 'summary') lsRenderSummary();
  else if(_lsView === 'trends') renderPFTrends();
  else lsRenderFull();
}

function lsUpdateKPIs(){
  const n = _lsFiltered.length;
  const prices = _lsFiltered.map(r=>r.price).filter(Boolean);
  const sqftRates = _lsFiltered
    .filter(r=>r.price_per_sqft)
    .map(r => r.price_per_sqft)
    .concat(_lsFiltered.filter(r=>!r.price_per_sqft && r.price && r.area_sqft && r.area_sqft > 0)
    .map(r => r.price / r.area_sqft));
  const types = new Set(_lsFiltered.map(r=>r.type).filter(Boolean));
  const avg   = prices.length ? Math.round(prices.reduce((a,b)=>a+b,0)/prices.length) : null;
  const avgSF = sqftRates.length ? Math.round(sqftRates.reduce((a,b)=>a+b,0)/sqftRates.length) : null;
  const fmtM  = v => v==null?'—':v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e3?(v/1e3).toFixed(0)+'K':v.toLocaleString();
  document.getElementById('ls-kpi-n').textContent     = n.toLocaleString();
  document.getElementById('ls-kpi-avg').textContent   = fmtM(avg);
  document.getElementById('ls-kpi-sqft').textContent  = avgSF ? avgSF.toLocaleString() : '—';
  document.getElementById('ls-kpi-types').textContent = types.size || '—';
}

function lsRenderSummary(){
  if(_lsDtSummary){ _lsDtSummary.destroy(); _lsDtSummary = null; }
  $('#ls-summary-table tbody').empty();
  // Group by district + type + beds
  const map = {};
  _lsFiltered.forEach(r => {
    const k = (r.district||'Unknown') + '||' + (r.type||'Other') + '||' + (r.beds||'Unknown');
    if(!map[k]) map[k] = {district:r.district||'Unknown', type:r.type||'Other', beds:r.beds||'Unknown', prices:[], rates:[]};
    if(r.price) map[k].prices.push(r.price);
    const ppsf = r.price_per_sqft || (r.price && r.area_sqft && r.area_sqft > 0 ? Math.round(r.price/r.area_sqft) : null); if(ppsf) map[k].rates.push(ppsf);
  });
  const rows = Object.values(map).map(g => {
    const n   = g.prices.length;
    const avg = n ? Math.round(g.prices.reduce((a,b)=>a+b,0)/n) : null;
    const mn  = n ? Math.min(...g.prices) : null;
    const mx  = n ? Math.max(...g.prices) : null;
    const rAvg = g.rates.length ? Math.round(g.rates.reduce((a,b)=>a+b,0)/g.rates.length) : null;
    return [
      g.district, g.type, g.beds, n,
      avg  != null ? avg.toLocaleString()  : '—',
      mn   != null ? mn.toLocaleString()   : '—',
      mx   != null ? mx.toLocaleString()   : '—',
      rAvg != null ? rAvg.toLocaleString() : '—',
    ];
  });
  _lsDtSummary = $('#ls-summary-table').DataTable({
    data: rows, pageLength: 25, order: [[3, 'desc']], dom: '<"dt-top"lf>rt<"dt-foot"ip>',
    language: _dtLang, columnDefs: [{targets:[3,4,5,6,7], className:'dt-right'}]
  });
}

function lsRenderFull(){
  const savedSearch = _lsDtFull ? _lsDtFull.search() : '';
  if(_lsDtFull){ _lsDtFull.destroy(); _lsDtFull = null; }
  $('#ls-full-table tbody').empty();
  const rows = _lsFiltered.map(r => {
    const sqft_rate = (r.price && r.area_sqft && r.area_sqft > 0)
      ? Math.round(r.price / r.area_sqft).toLocaleString() : '—';
    const link = r.url
      ? `<a class="ls-link" href="${r.url}" target="_blank" rel="noopener">View →</a>`
      : '—';
    return [
      r.title || '—', r.community || '—', r.type || '—', r.beds || '—', r.district || '—',
      r.sale_type || '—',
      r.price ? r.price.toLocaleString() : '—',
      r.area_sqft ? r.area_sqft.toLocaleString() : '—',
      sqft_rate, link
    ];
  });
  _lsDtFull = $('#ls-full-table').DataTable({
    data: rows, pageLength: 50, order: [[6, 'desc']], dom: '<"dt-top"lf>rt<"dt-foot"ip>',
    language: _dtLang,
    search: { search: savedSearch },
    columnDefs: [
      {targets:[6,7,8], className:'dt-right'},
      {targets:9, orderable:false}
    ]
  });
}

function lsSetView(view){
  _lsView = view;
  document.getElementById('ls-btn-summary').classList.toggle('on', view==='summary');
  document.getElementById('ls-btn-full').classList.toggle('on', view==='full');
  document.getElementById('ls-btn-trends').classList.toggle('on', view==='trends');
  document.getElementById('ls-summary-card').style.display = view==='summary' ? '' : 'none';
  document.getElementById('ls-full-card').style.display    = view==='full'    ? '' : 'none';
  document.getElementById('ls-trends-card').style.display  = view==='trends'  ? '' : 'none';
  if(view==='summary') lsRenderSummary();
  else if(view==='trends') renderPFTrends();
  else lsRenderFull();
}

// ── PF Trends ─────────────────────────────────────────────────────────────────
function _lsFilteredSeries(){
  const series = (PF_TREND_DATA && PF_TREND_DATA.series) ? PF_TREND_DATA.series : [];
  return series.filter(s => {
    if(_lsFilter.type.size     && !_lsFilter.type.has(s.type))         return false;
    if(_lsFilter.beds.size     && !_lsFilter.beds.has(s.beds))         return false;
    if(_lsFilter.district.size && !_lsFilter.district.has(s.district)) return false;
    return true;
  });
}

function renderPFTrends(){
  const months    = (PF_TREND_DATA && PF_TREND_DATA.months) ? PF_TREND_DATA.months : [];
  const snapCount = months.length;
  const meta = document.getElementById('ls-trends-meta');
  if(meta){
    if(snapCount === 0) meta.textContent = 'No snapshots yet — run build to collect first snapshot';
    else meta.textContent = `${snapCount} monthly snapshot${snapCount>1?'s':''} · ${months[0]} → ${months[months.length-1]}`;
  }
  const noteEl = document.getElementById('ls-trends-note');
  if(noteEl) noteEl.style.display = snapCount <= 1 ? '' : 'none';
  renderTrendChart();
  renderTrendTable();
}

function renderTrendChart(){
  const el = document.getElementById('ls-trends-chart');
  if(!el) return;
  let ch = echarts.getInstanceByDom(el);
  if(!ch) ch = echarts.init(el, null, {renderer:'canvas'});
  const months   = (PF_TREND_DATA && PF_TREND_DATA.months) ? PF_TREND_DATA.months : [];
  const filtered = _lsFilteredSeries();
  const top10    = filtered.slice(0, 10);
  const fmtP = v => v==null?'—':v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e3?(v/1e3).toFixed(0)+'K':v.toLocaleString();

  if(months.length <= 1){
    // Single snapshot — horizontal bar chart of avg prices
    const barItems = top10
      .map(s => ({ name: s.district+' · '+s.type+' · '+s.beds, value: s.monthly_avg[0]||null }))
      .filter(d => d.value)
      .sort((a,b) => b.value - a.value);
    ch.setOption({
      backgroundColor:'transparent',
      grid:{top:8, right:80, bottom:8, left:200, containLabel:false},
      tooltip:{
        trigger:'axis', backgroundColor:'#1A1714', borderColor:'#1A1714',
        textStyle:{color:'#fff', fontFamily:'Inter', fontSize:12},
        formatter: p => `<b>${p[0].name}</b><br/>Avg Price: <b>AED ${(p[0].value||0).toLocaleString()}</b>`
      },
      xAxis:{
        type:'value', splitLine:{lineStyle:{color:'#f1f5f9'}},
        axisLabel:{color:'#94a3b8', fontSize:10, formatter: v => fmtP(v)}
      },
      yAxis:{
        type:'category', data: barItems.map(d=>d.name), inverse:true,
        axisLine:{lineStyle:{color:'#e2e8f0'}}, axisTick:{show:false},
        axisLabel:{color:'#6B6560', fontSize:11, width:190, overflow:'truncate'}
      },
      series:[{
        type:'bar', data: barItems.map(d=>d.value),
        itemStyle:{color:'#D4761A', borderRadius:[0,3,3,0]},
        barMaxWidth:28,
        label:{show:true, position:'right', formatter: p => fmtP(p.value), fontSize:10, color:'#6B6560'}
      }]
    }, true);
  } else {
    // Multi-month — line chart
    const palette = ['#D4761A','#2563EB','#10B981','#8B5CF6','#EF4444','#F59E0B','#06B6D4','#EC4899','#84CC16','#6366F1'];
    const seriesList = top10.map((s, i) => ({
      name: s.district+' · '+s.type+' · '+s.beds,
      type:'line', data: s.monthly_avg, connectNulls:true, smooth:0.3,
      symbol:'circle', symbolSize:6,
      lineStyle:{color:palette[i%palette.length], width:2},
      itemStyle:{color:palette[i%palette.length], borderColor:'#fff', borderWidth:1.5}
    }));
    ch.setOption({
      backgroundColor:'transparent',
      grid:{top:8, right:16, bottom:80, left:80},
      legend:{
        data: top10.map(s => s.district+' · '+s.type+' · '+s.beds),
        bottom:0, type:'scroll', itemWidth:16, itemHeight:3,
        textStyle:{color:'#94a3b8', fontSize:9}, icon:'roundRect'
      },
      tooltip:{
        trigger:'axis', backgroundColor:'#1A1714', borderColor:'#1A1714',
        textStyle:{color:'#fff', fontFamily:'Inter', fontSize:12},
        formatter: params => {
          let html = `<b>${params[0].axisValue}</b>`;
          params.forEach(p => {
            if(p.value != null)
              html += `<br/>${p.marker} ${p.seriesName}: <b>AED ${p.value.toLocaleString()}</b>`;
          });
          return html;
        }
      },
      xAxis:{
        type:'category', data:months,
        axisLine:{lineStyle:{color:'#e2e8f0'}}, axisTick:{show:false},
        axisLabel:{color:'#94a3b8', fontSize:10}
      },
      yAxis:{
        type:'value', splitLine:{lineStyle:{color:'#f1f5f9'}},
        axisLabel:{color:'#94a3b8', fontSize:10, formatter: v => fmtP(v)}
      },
      series: seriesList
    }, true);
  }
  ch.resize();
}

function renderTrendTable(){
  if(_lsDtTrend){ _lsDtTrend.destroy(); _lsDtTrend = null; }
  $('#ls-trend-table tbody').empty();
  const filtered = _lsFilteredSeries();
  const rows = filtered.map(s => {
    let firstAvg = null, lastAvg = null, firstIdx = -1, lastIdx = -1;
    for(let i = 0; i < s.monthly_avg.length; i++){
      if(s.monthly_avg[i] != null){
        if(firstIdx < 0){ firstIdx = i; firstAvg = s.monthly_avg[i]; }
        lastIdx = i; lastAvg = s.monthly_avg[i];
      }
    }
    const monthsTracked = s.monthly_count.filter(c => c > 0).length;
    let deltaAed = null, deltaPct = null;
    if(firstAvg != null && lastAvg != null && firstIdx !== lastIdx){
      deltaAed = lastAvg - firstAvg;
      deltaPct = firstAvg > 0 ? ((deltaAed / firstAvg) * 100).toFixed(1) : null;
    }
    const fmtN   = v => v != null ? v.toLocaleString() : '—';
    const dSign  = v => v == null ? '—' : (v >= 0 ? '+' : '') + v.toLocaleString();
    const pSign  = v => v == null ? '—' : (parseFloat(v) >= 0 ? '+' : '') + v + '%';
    return [
      s.district, s.type, s.beds, monthsTracked,
      fmtN(firstAvg), fmtN(lastAvg),
      dSign(deltaAed), pSign(deltaPct)
    ];
  });
  _lsDtTrend = $('#ls-trend-table').DataTable({
    data: rows, pageLength:25, order:[[3,'desc']], dom:'<"dt-top"lf>rt<"dt-foot"ip>',
    language:_dtLang,
    columnDefs:[
      {targets:[3,4,5,6,7], className:'dt-right'},
      {targets:6, createdCell:(cell, val) => {
        const v = parseFloat((val||'').replace(/[^0-9.\-]/g,''));
        if(!isNaN(v)) cell.className += v >= 0 ? ' diff-up' : ' diff-dn';
      }},
      {targets:7, createdCell:(cell, val) => {
        const v = parseFloat(val);
        if(!isNaN(v)) cell.className += v >= 0 ? ' diff-up' : ' diff-dn';
      }}
    ]
  });
}

function exportPFCSV(){
  const data = _lsFiltered.length ? _lsFiltered : PF_DATA;
  const hdrs = ['Title','Type','Beds','Bedrooms','District','Community','Sale Type','Price (AED)','Area (sqft)','AED/sqft','Listed Date','URL'];
  const lines = [hdrs.join(',')];
  data.forEach(r => {
    const sqft_rate = (r.price && r.area_sqft && r.area_sqft > 0) ? Math.round(r.price/r.area_sqft) : '';
    const ppsf2 = r.price_per_sqft || ((r.price && r.area_sqft && r.area_sqft > 0) ? Math.round(r.price/r.area_sqft) : '');
    lines.push([
      `"${(r.title||'').replace(/"/g,'""')}"`,
      r.type||'', r.beds||'', r.beds||'',
      `"${(r.district||'').replace(/"/g,'""')}"`,
      `"${(r.community||'').replace(/"/g,'""')}"`,
      r.sale_type||'',
      r.price||'', r.area_sqft||'', ppsf2,
      r.date ? r.date.slice(0,10) : '',
      r.url||''
    ].join(','));
  });
  const blob = new Blob([lines.join('\n')], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'pf_abu_dhabi_listings.csv';
  a.click();
}


// ── Insights ──────────────────────────────────────────────────────────────────
let _insDtTop10 = null, _insDtInsAll = null;

// ── Normalisation helpers ──────────────────────────────────────────────────────
function _normComm(s){ return (s||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim(); }
function _normType(s){
  const t=(s||'').toLowerCase();
  if(t.includes('apartment')) return 'apartment';
  if(t.includes('townhouse')) return 'townhouse';
  if(t.includes('villa'))     return 'villa';
  return t.replace(/\s+/g,' ').trim();
}
function _normBeds(s){
  const t=(s||'').toLowerCase();
  if(t.includes('studio')) return 'studio';
  const m=t.match(/(\d+)/);
  return m ? m[1]+'bed' : 'other';
}

function renderInsights(){
  const txData = _currentFiltered || TABLE_DATA;
  document.getElementById('ins-tx-count').textContent = txData.length.toLocaleString();
  document.getElementById('ins-pf-count').textContent = PF_DATA.length.toLocaleString();

  const SQFT_TO_SQM = 10.764;
  const now   = new Date();
  const d6mo  = new Date(now.getFullYear(), now.getMonth()-6,  1);
  const d12mo = new Date(now.getFullYear(), now.getMonth()-12, 1);
  const med   = arr => { if(!arr.length) return null; const s=[...arr].sort((a,b)=>a-b); return s[Math.floor(s.length/2)]; };

  // ── TX map: key = normType|normBeds|normComm ──────────────────────────────
  const txMap = {};
  txData.forEach(r => {
    if(!r.co || !r.r) return;
    const k = _normType(r.ty)+'|'+_normBeds(r.la)+'|'+_normComm(r.co);
    if(!txMap[k]) txMap[k] = {co:r.co, ty:r.ty||'', la:r.la||'', di:r.di||'', rates:[], recent:[], prior:[]};
    txMap[k].rates.push(r.r);
    if(r.d){
      const dt=new Date(r.d);
      if(dt>=d6mo)       txMap[k].recent.push(r.r);
      else if(dt>=d12mo) txMap[k].prior.push(r.r);
    }
  });

  // ── PF map: key = normType|normBeds|normComm ──────────────────────────────
  const pfMap = {};
  PF_DATA.forEach(r => {
    if(!r.community) return;
    const k = _normType(r.type)+'|'+_normBeds(r.beds)+'|'+_normComm(r.community);
    if(!pfMap[k]) pfMap[k] = {co:r.community, ty:r.type||'', beds:r.beds||'', rates_sqm:[], count:0};
    pfMap[k].count++;
    let rSqm = r.price_per_sqft ? r.price_per_sqft * SQFT_TO_SQM
             : (r.price && r.area_sqft > 0) ? r.price / r.area_sqft * SQFT_TO_SQM : null;
    if(rSqm) pfMap[k].rates_sqm.push(rSqm);
  });

  // ── Match & compute metrics per group ─────────────────────────────────────
  const insights = [];
  Object.entries(pfMap).forEach(([pfKey, pf]) => {
    if(pf.count < 2 || !pf.rates_sqm.length) return;
    const [pfType, pfBeds, pfComm] = pfKey.split('|');
    const tbPfx = pfType+'|'+pfBeds+'|';

    // Exact match first, then partial community match within same type+beds
    let tx = txMap[pfKey];
    if(!tx){
      const match = Object.keys(txMap).filter(k=>k.startsWith(tbPfx)).find(k=>{
        const tc=k.slice(tbPfx.length);
        return tc===pfComm || tc.includes(pfComm) || pfComm.includes(tc);
      });
      if(match) tx = txMap[match];
    }
    if(!tx || tx.rates.length < 5) return;

    const askMed = med(pf.rates_sqm);
    const txMed  = med(tx.rates);
    const txRecent = med(tx.recent);
    const txPrior  = med(tx.prior);
    if(!askMed || !txMed) return;

    // Ask vs Sale: + = ask BELOW historical (good for buyer), − = ask ABOVE historical
    const vsMarket = (txMed - askMed) / txMed * 100;
    // 6M Trend: − = prices falling (softening), + = rising
    const trend = (txRecent && txPrior) ? (txRecent - txPrior) / txPrior * 100 : null;
    // Neg. Gap: + = ask above hist (room to negotiate), − = ask already below hist
    const negGap = (askMed - txMed) / askMed * 100;

    // Attractiveness: purely how much cheaper the ask is vs historical sale price
    // Positive vsMarket = ask is BELOW historical = attractive
    const score  = vsMarket;
    const signal = vsMarket > 5 ? 'buy' : vsMarket > -5 ? 'neutral' : 'above';

    insights.push({
      co:pf.co, ty:pf.ty, beds:pf.beds, di:tx.di,
      pf_count:pf.count, tx_count:tx.rates.length,
      ask_rate:Math.round(askMed), tx_rate:Math.round(txMed),
      vs_market:vsMarket, trend:trend, neg_gap:negGap,
      score:score, signal:signal
    });
  });

  insights.sort((a,b) => b.score - a.score);

  const fmtPct = v => v==null ? '—' : (v>=0?'+':'')+v.toFixed(1)+'%';
  const sigLabel = s => s==='buy' ? 'Buy Signal' : s==='neutral' ? 'Neutral' : 'Above Market';
  const sigClass = s => s==='buy' ? 'ins-sig ins-buy' : s==='neutral' ? 'ins-sig ins-neutral' : 'ins-sig ins-above';

  // render(d, type, row) helpers — wrap with color span for display, raw value for sort/filter
  const pctRender = (invert) => (d,t) => {
    if(t!=='display' || d==='—') return d;
    const v=parseFloat(d); if(isNaN(v)) return d;
    const good = invert ? v<0 : v>0;
    const bad  = invert ? v>0 : v<0;
    const cls  = good?'diff-up':bad?'diff-dn':'';
    return cls ? `<span class="${cls}">${d}</span>` : d;
  };
  const sigRender = (d,t,row) => t==='display'
    ? `<span class="${sigClass(row[row.length-1])}">${d}</span>` : d;

  // ── Top 10 ────────────────────────────────────────────────────────────────
  const top10Rows = insights.slice(0,10).map((c,i) => [
    i+1, c.co, c.ty, c.beds, c.di,
    c.pf_count, c.ask_rate.toLocaleString(), c.tx_rate.toLocaleString(),
    fmtPct(c.vs_market), fmtPct(c.trend), fmtPct(c.neg_gap),
    sigLabel(c.signal), c.signal  // col 12 = hidden signal key
  ]);
  if(_insDtTop10){ _insDtTop10.destroy(); _insDtTop10=null; }
  $('#ins-top10-table tbody').empty();
  _insDtTop10 = $('#ins-top10-table').DataTable({
    data: top10Rows,
    paging:false, searching:false, ordering:true, order:[[0,'asc']],
    dom:'<"dt-top">rt', language:_dtLang,
    columnDefs:[
      {targets:[5,6,7], className:'dt-right'},
      {targets:8,  className:'dt-right', render:pctRender(false)},  // vs market: + = good
      {targets:9,  className:'dt-right', render:pctRender(true)},   // trend: − = good
      {targets:10, className:'dt-right', render:pctRender(true)},   // neg gap: − = already below
      {targets:11, render:sigRender},
      {targets:12, visible:false}
    ]
  });

  // ── Full table ─────────────────────────────────────────────────────────────
  const allRows = insights.map(c => [
    c.co, c.ty, c.beds, c.di,
    c.pf_count, c.tx_count, c.ask_rate.toLocaleString(), c.tx_rate.toLocaleString(),
    fmtPct(c.vs_market), fmtPct(c.trend), fmtPct(c.neg_gap),
    sigLabel(c.signal), c.signal  // col 12 = hidden signal key
  ]);
  if(_insDtInsAll){ _insDtInsAll.destroy(); _insDtInsAll=null; }
  $('#ins-full-table tbody').empty();
  _insDtInsAll = $('#ins-full-table').DataTable({
    data: allRows,
    pageLength:25, order:[[8,'desc']], dom:'<"dt-top"lf>rt<"dt-foot"ip>',
    language:_dtLang,
    columnDefs:[
      {targets:[4,5,6,7], className:'dt-right'},
      {targets:8,  className:'dt-right', render:pctRender(false)},
      {targets:9,  className:'dt-right', render:pctRender(true)},
      {targets:10, className:'dt-right', render:pctRender(true)},
      {targets:11, render:sigRender},
      {targets:12, visible:false}
    ]
  });
}

// ── CSV Upload ────────────────────────────────────────────────────────────────
function openUploadOverlay(){
  document.getElementById('upload-overlay').classList.add('show');
  const box = document.getElementById('upload-box');
  // Drag-and-drop
  box.ondragover = e => { e.preventDefault(); box.classList.add('drag-over'); };
  box.ondragleave = () => box.classList.remove('drag-over');
  box.ondrop = e => {
    e.preventDefault();
    box.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if(file && file.name.endsWith('.csv')) processUploadFile(file);
  };
}

function closeUploadOverlay(e){
  if(e && e.target !== document.getElementById('upload-overlay')) return;
  document.getElementById('upload-overlay').classList.remove('show');
}

function handleCSVUpload(event){
  const file = event.target.files[0];
  if(!file) return;
  event.target.value = '';  // allow re-uploading same file
  document.getElementById('upload-overlay').classList.remove('show');
  processUploadFile(file);
}

function processUploadFile(file){
  showUploadToast('⏳', 'Parsing ' + file.name + '…');
  Papa.parse(file, {
    header: true,
    skipEmptyLines: true,
    encoding: 'UTF-8',
    complete: results => {
      try {
        const rows = cleanCSVRows(results.data);
        if(!rows.length){ showUploadToast('⚠️', 'No valid rows found after cleaning.'); return; }
        TABLE_DATA = rows;
        initLookups();
        // Refresh all UI
        document.getElementById('date-from').value = minDate;
        document.getElementById('date-to').value   = maxDate;
        document.getElementById('tx-count').textContent = TABLE_DATA.length.toLocaleString() + ' tx';
        Object.keys(filterState).forEach(k => filterState[k].clear());
        ['type','layout','saletype','district'].forEach(dim => {
          const items = dim==='type'?allTypes:dim==='layout'?allLayouts:dim==='saletype'?allSaleTypes:allDistricts;
          buildChecklist('cl-'+dim, items, dim);
          updateFsBadge(dim);
        });
        _currentFiltered = null;
        initTableWith(TABLE_DATA);
        updateKPIs(TABLE_DATA);
        showUploadToast('✅', rows.length.toLocaleString() + ' transactions loaded');
      } catch(err) {
        showUploadToast('❌', 'Error: ' + err.message);
      }
    },
    error: err => showUploadToast('❌', 'Parse error: ' + err.message)
  });
}

function cleanCSVRows(raw){
  const ALLOWED_TYPES = new Set(['apartment','villa','townhouse / attached villa']);
  const ALLOWED_SEQ   = new Set(['primary','secondary']);
  const g = (r,k) => (r[k] || '').toString().trim();
  const titleCase = s => s ? s.replace(/\w/g, ch => ch.toUpperCase()) : '';

  let rows = [];
  for(const r of raw){
    // Date
    const ds = g(r,'Sale Application Date');
    if(!ds) continue;
    const dt = new Date(ds);
    if(isNaN(dt.getTime())) continue;
    const d = dt.toISOString().slice(0,10);

    // Sold share == 1.0
    if(parseFloat(g(r,'Property Sold Share')) !== 1.0) continue;

    // Sale sequence
    if(!ALLOWED_SEQ.has(g(r,'Sale Sequence').toLowerCase())) continue;

    // Asset class
    if(g(r,'Asset Class').toLowerCase() !== 'residential') continue;

    // Sale type
    const st = g(r,'Sale Application Type').toLowerCase();
    if(st === 'court-mandated') continue;

    // Property type
    const tyRaw = g(r,'Property Type').toLowerCase();
    if(!ALLOWED_TYPES.has(tyRaw)) continue;

    // Price
    const p = parseFloat(g(r,'Property Sale Price (AED)'));
    if(isNaN(p) || p < 50000) continue;

    // Area & rate
    let a = parseFloat(g(r,'Property Sold Area (SQM)'));
    if(isNaN(a)) a = null;
    let rate = parseFloat(g(r,'Rate (AED per SQM)'));
    if(isNaN(rate)) rate = (a && a > 0) ? p / a : null;

    rows.push({
      d,
      di: titleCase(g(r,'District').toLowerCase()),
      co: titleCase(g(r,'Community').toLowerCase()),
      pr: g(r,'Project Name'),
      ty: titleCase(tyRaw),
      la: titleCase(g(r,'Property Layout').toLowerCase()),
      p:  Math.round(p),
      a:  a != null ? Math.round(a * 10) / 10 : null,
      r:  rate != null ? Math.round(rate) : null,
      st,
    });
  }

  // Price outlier cap: global 99th percentile
  if(rows.length > 0){
    const prices = rows.map(r=>r.p).filter(Boolean).sort((a,b)=>a-b);
    const cap = prices[Math.floor(prices.length * 0.99)] || Infinity;
    rows = rows.filter(r => r.p == null || r.p <= cap);
  }
  return rows;
}

let _toastTimer = null;
function showUploadToast(icon, msg){
  const el = document.getElementById('upload-toast');
  document.getElementById('upload-toast-icon').textContent = icon;
  document.getElementById('upload-toast-msg').textContent  = msg;
  el.style.display = 'block';
  if(_toastTimer) clearTimeout(_toastTimer);
  // Auto-hide success/warning after 4s; keep error visible longer
  const delay = icon === '✅' ? 4000 : icon === '⏳' ? 60000 : 7000;
  _toastTimer = setTimeout(() => { el.style.display = 'none'; }, delay);
}

// ── Initialise ────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initLookups();
  document.getElementById('date-from').value = minDate;
  document.getElementById('date-to').value   = maxDate;
  document.getElementById('tx-count').textContent = TABLE_DATA.length.toLocaleString() + ' tx';

  buildChecklist('cl-type',     allTypes,     'type');
  buildChecklist('cl-layout',   allLayouts,   'layout');
  buildChecklist('cl-saletype', allSaleTypes, 'saletype');
  buildChecklist('cl-district', allDistricts, 'district');

  initTableWith(TABLE_DATA);
  updateKPIs(TABLE_DATA);
});
</script>
</body>
</html>
"""


# ─── PF History helpers ──────────────────────────────────────────────────────
def load_pf_history() -> dict:
    if PF_HISTORY_PATH.exists():
        try:
            return json.loads(PF_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"snapshots": []}


def maybe_add_pf_snapshot(listings: list, history: dict) -> dict:
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    existing = next((s for s in history["snapshots"] if s["month"] == current_month), None)
    if existing:
        print(f"  PF: using stored snapshot for {current_month} (already in history)")
        return history
    snapshot = {
        "month": current_month,
        "collected_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "listings_count": len(listings),
        "listings": listings,
    }
    history["snapshots"].append(snapshot)
    history["snapshots"].sort(key=lambda s: s["month"])
    try:
        PF_HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
        print(f"  PF history: saved snapshot for {current_month} ({len(listings):,} listings)")
    except Exception as e:
        print(f"  PF history: write error — {e}")
    return history


def build_pf_trend_data(history: dict) -> dict:
    """Aggregate per (district, type, beds) per month for trend charts."""
    snapshots = history.get("snapshots", [])
    months = sorted(set(s["month"] for s in snapshots))
    if not months:
        return {"months": [], "series": []}

    # Aggregate: key -> month -> list of prices
    agg: dict = {}
    for snap in snapshots:
        m = snap["month"]
        for listing in snap.get("listings", []):
            district = (listing.get("district") or "Unknown").strip()
            ptype    = (listing.get("type") or "Other").strip()
            beds     = (listing.get("beds") or "Unknown").strip()
            price    = listing.get("price")
            if not price:
                continue
            key = f"{district}|{ptype}|{beds}"
            if key not in agg:
                agg[key] = {}
            if m not in agg[key]:
                agg[key][m] = []
            agg[key][m].append(price)

    series = []
    for key, month_data in agg.items():
        # Must have >= 3 listings in at least 1 month
        if not any(len(v) >= 3 for v in month_data.values()):
            continue
        parts = key.split("|", 2)
        district, ptype, beds = parts[0], parts[1], parts[2]
        monthly_avg: list   = []
        monthly_med: list   = []
        monthly_count: list = []
        total = 0
        for m in months:
            prices = month_data.get(m, [])
            n = len(prices)
            monthly_count.append(n)
            total += n
            if n > 0:
                monthly_avg.append(round(sum(prices) / n))
                sp = sorted(prices)
                monthly_med.append(sp[len(sp) // 2])
            else:
                monthly_avg.append(None)
                monthly_med.append(None)
        series.append({
            "key": key,
            "district": district,
            "type": ptype,
            "beds": beds,
            "monthly_avg": monthly_avg,
            "monthly_med": monthly_med,
            "monthly_count": monthly_count,
            "_total": total,
        })

    series.sort(key=lambda s: s["_total"], reverse=True)
    for s in series:
        del s["_total"]

    return {"months": months, "series": series}


# ─── Build ───────────────────────────────────────────────────────────────────
def build():
    from datetime import datetime
    df = load_data()

    # Serialize transactions
    table_data = build_table_data(df)

    # PF History — reuse stored snapshot for current month if available
    history = load_pf_history()
    current_month = datetime.now().strftime("%Y-%m")
    existing = next((s for s in history["snapshots"] if s["month"] == current_month), None)
    if existing:
        print(f"  PF: using stored snapshot for {current_month}")
        pf_listings = existing["listings"]
    else:
        print("Fetching Property Finder listings…")
        pf_listings = fetch_propertyfinder()
        if pf_listings:
            history = maybe_add_pf_snapshot(pf_listings, history)

    pf_trend_data = build_pf_trend_data(history)

    print("Assembling HTML…")

    table_json    = json.dumps(table_data,    separators=(',',':'), ensure_ascii=False)
    pf_json       = json.dumps(pf_listings,   separators=(',',':'), ensure_ascii=False)
    pf_trend_json = json.dumps(pf_trend_data, separators=(',',':'), ensure_ascii=False)
    tx_count      = f"{len(df):,}"
    latest_snap   = history["snapshots"][-1]["month"] if history["snapshots"] else ""

    html = HTML_TEMPLATE
    html = html.replace('__TABLE_DATA__',       table_json)
    html = html.replace('__PF_DATA__',          pf_json)
    html = html.replace('__PF_TREND_DATA__',    pf_trend_json)
    html = html.replace('__TX_COUNT__',         tx_count)
    html = html.replace('__PF_SNAP_MONTH__',    latest_snap)

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / 1_048_576
    print(f"\n✅  index.html written → {OUTPUT_PATH}")
    print(f"    File size: {size_mb:.1f} MB")
    print(f"    Table rows: {len(table_data):,}")
    print(f"    PF listings: {len(pf_listings):,}")
    print(f"    PF history snapshots: {len(history['snapshots'])}")
    print(f"    PF trend series: {len(pf_trend_data['series'])}")


if __name__ == "__main__":
    build()
