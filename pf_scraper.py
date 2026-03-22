"""
pf_scraper.py — Property Finder scraping functions for the Streamlit dashboard.
Extracted from build_mashvisor.py.
"""
import json
import time
import re as _re
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

BASE_DIR = Path(__file__).parent
PF_CACHE_PATH   = BASE_DIR / "pf_cache.json"
PF_HISTORY_PATH = BASE_DIR / "pf_history.json"

PF_BASE_URL = "https://www.propertyfinder.ae/en/buy/abu-dhabi/properties-for-sale.html"


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
    nd_m = _re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, _re.DOTALL
    )
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
        district = _pf_district(path_name) if path_name else community

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


def fetch_propertyfinder(cutoff_days: int = 30, max_pages: int = 60,
                         rate_sleep: float = 1.2, force: bool = False) -> list:
    """Scrape Property Finder Abu Dhabi for-sale listings.

    Uses a 24h file-based cache. Pass force=True to bypass the cache.
    Returns a list of listing dicts.
    """
    # Check 24h cache
    if not force and PF_CACHE_PATH.exists():
        try:
            cached = json.loads(PF_CACHE_PATH.read_text(encoding="utf-8"))
            age_h = (time.time() - cached.get("ts", 0)) / 3600
            if age_h < 24:
                return cached["listings"]
        except Exception:
            pass

    if not _HAS_REQUESTS:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=cutoff_days)
    all_listings = []
    seen_ids: set = set()

    for page in range(1, max_pages + 1):
        url = f"{PF_BASE_URL}?sort=nd&page={page}"
        try:
            resp = _requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 404:
                break
            if resp.status_code != 200:
                break
            items = _pf_parse_page(resp.text)
            if not items:
                break

            page_listings = []
            all_old = True  # track if every dated listing on this page is past cutoff
            for r in items:
                uid = r.get("url") or r.get("title", "")
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                if r["date"]:
                    try:
                        listed_dt = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                        if listed_dt < cutoff_dt:
                            continue
                        all_old = False
                    except Exception:
                        all_old = False
                else:
                    all_old = False
                page_listings.append(r)

            all_listings.extend(page_listings)

            # Early exit: if every listing on this page predates the cutoff, stop paging
            if all_old and len(items) > 0:
                break

            time.sleep(rate_sleep)

        except Exception:
            break

    try:
        PF_CACHE_PATH.write_text(
            json.dumps({"ts": time.time(), "listings": all_listings},
                       ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
    except Exception:
        pass

    return all_listings


def _migrate_snapshot_keys(history: dict) -> tuple[dict, bool]:
    """Migrate old YYYY-MM snapshot keys to YYYY-MM-01 format.

    Returns (migrated_history, was_changed).
    """
    changed = False
    snapshots = history.get("snapshots", [])
    for s in snapshots:
        key = s.get("month", "")
        # Old format: exactly 7 chars like "2026-03"
        if len(key) == 7 and key[4] == "-":
            s["month"] = key + "-01"
            changed = True
    history["snapshots"] = snapshots
    return history, changed


def load_pf_history() -> dict:
    """Load pf_history.json, migrating old YYYY-MM keys to YYYY-MM-DD on the fly."""
    if not PF_HISTORY_PATH.exists():
        return {"snapshots": []}
    try:
        history = json.loads(PF_HISTORY_PATH.read_text(encoding="utf-8"))
        history, changed = _migrate_snapshot_keys(history)
        if changed:
            # Persist the migrated keys immediately
            PF_HISTORY_PATH.write_text(
                json.dumps(history, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        return history
    except Exception:
        return {"snapshots": []}


def _dedup_listings(listings: list) -> list:
    """Deduplicate a list of PF listing dicts by URL (falling back to title)."""
    seen: set = set()
    result = []
    for item in listings:
        uid = item.get("url") or item.get("title", "")
        if uid and uid in seen:
            continue
        if uid:
            seen.add(uid)
        result.append(item)
    return result


def save_pf_snapshot(listings: list, label: str | None = None, force: bool = False) -> str:
    """Save a dated snapshot to pf_history.json.

    Uses YYYY-MM-DD key (supports weekly snapshots without overwriting).
    Deduplicates listings by URL before saving.
    Pass force=True to overwrite an existing snapshot for the same date.
    Returns the snapshot key used.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    key = label or today

    # Deduplicate listings within this snapshot
    listings = _dedup_listings(listings)

    history = load_pf_history()
    snapshots = history.get("snapshots", [])

    existing_keys = {s.get("month") for s in snapshots}
    if key in existing_keys:
        if not force:
            return key  # already saved, skip
        # Overwrite: remove old snapshot for this key
        snapshots = [s for s in snapshots if s.get("month") != key]

    snapshots.append({
        "month": key,
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
        "listings_count": len(listings),
        "listings": listings,
    })

    # Keep sorted by date key
    snapshots.sort(key=lambda s: s.get("month", ""))

    try:
        PF_HISTORY_PATH.write_text(
            json.dumps({"snapshots": snapshots}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
    except Exception:
        pass

    return key


def get_cache_info() -> dict:
    """Return metadata about the current cache file."""
    if not PF_CACHE_PATH.exists():
        return {"exists": False, "age_hours": None, "count": 0}
    try:
        cached = json.loads(PF_CACHE_PATH.read_text(encoding="utf-8"))
        age_h = (time.time() - cached.get("ts", 0)) / 3600
        return {
            "exists": True,
            "age_hours": round(age_h, 1),
            "count": len(cached.get("listings", [])),
            "ts": cached.get("ts", 0),
        }
    except Exception:
        return {"exists": False, "age_hours": None, "count": 0}
