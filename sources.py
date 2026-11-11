"""Run Apify scrapers through the REST API and map their rows to one shape.

Uses plain HTTP (requests) rather than the Apify client library, so there is one
small dependency and nothing changes if the client's interface does.
"""
import os
import time

import requests

import extract

API = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

SCRAPER_A = "scrapersdelight~realestate-com-au-scraper"  # primary candidate
SCRAPER_B = "abotapi~realestate-au-scraper"  # comparison


class ApifyError(RuntimeError):
    pass


def _session():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise ApifyError("APIFY_TOKEN is not set. See README, step 2.")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    return s


def run_actor(actor_id, run_input, max_charge_usd=2.0, timeout_s=1800):
    """Start an actor, wait for it, and return (items, run_info)."""
    s = _session()
    r = s.post(
        f"{API}/acts/{actor_id}/runs",
        params={"maxTotalChargeUsd": max_charge_usd},
        json=run_input,
        timeout=60,
    )
    if r.status_code >= 400:
        raise ApifyError(f"{actor_id} would not start ({r.status_code}): {r.text[:400]}")
    run = r.json()["data"]
    started = time.time()
    while run["status"] not in TERMINAL:
        if time.time() - started > timeout_s:
            raise ApifyError(f"{actor_id} still running after {timeout_s // 60} min; run id {run['id']}")
        r = s.get(f"{API}/actor-runs/{run['id']}", params={"waitForFinish": 60}, timeout=90)
        r.raise_for_status()
        run = r.json()["data"]
        print(f"  {actor_id}: {run['status']} ({int(time.time() - started)} s)")
    if run["status"] != "SUCCEEDED":
        msg = run.get("statusMessage") or ""
        raise ApifyError(f"{actor_id} ended {run['status']}: {msg}; run id {run['id']}")

    items, offset = [], 0
    while True:
        r = s.get(
            f"{API}/datasets/{run['defaultDatasetId']}/items",
            params={"clean": "true", "format": "json", "offset": offset, "limit": 1000},
            timeout=120,
        )
        r.raise_for_status()
        batch = r.json()
        items.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    summary = None
    store = run.get("defaultKeyValueStoreId")
    if store:
        r = s.get(f"{API}/key-value-stores/{store}/records/RUN_SUMMARY", timeout=30)
        if r.status_code == 200:
            try:
                summary = r.json()
            except ValueError:
                summary = r.text[:2000]

    info = {
        "actor": actor_id,
        "run_id": run["id"],
        "status": run["status"],
        "seconds": run.get("stats", {}).get("runTimeSecs"),
        "usage_usd": run.get("usageTotalUsd"),
        "run_summary": summary,
    }
    return items, info


# ---------- inputs ----------

def input_a(suburb, state, postcode, max_price, max_results):
    return {
        "locations": [f"{suburb}, {state} {postcode}"],
        "listingType": "buy",
        "propertyTypes": ["house", "land"],
        "maxPrice": max_price,
        "includeSurroundingSuburbs": False,
        "includeProjects": True,
        "includeCoordinates": False,
        "includeDetails": False,
        "sortBy": "newest",
        "maxResults": max_results,
    }


def input_a_details(urls):
    """Listing URLs as input make scraper A open each listing page."""
    return {
        "startUrls": [{"url": u} for u in urls],
        "includeDetails": True,
        "includeCoordinates": False,
        "maxResults": len(urls),
    }


def input_b(suburb, state, postcode, max_price, max_results):
    return {
        "mode": "location",
        "locations": [{"suburb": suburb, "state": state, "postcode": postcode}],
        "listingType": "buy",
        "propertyTypes": ["house", "land"],
        "priceMax": max_price,
        "includeSurrounding": False,
        "maxListings": max_results,
        "maxPages": 0,
    }


# ---------- mapping ----------

def pick(item, *paths):
    """First non-empty value among dotted paths, e.g. pick(x, 'address.full', 'address')."""
    for path in paths:
        cur = item
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " | ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return " | ".join(f"{k}: {_as_text(v)}" for k, v in value.items())
    return str(value)


def _frontage_field(value):
    """A structured frontage field, if a scraper ever provides one: 12.5 or '12.5m'."""
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        m = extract.re.search(r"\d{1,2}(?:\.\d{1,2})?", value)
        v = float(m.group(0)) if m else None
    else:
        v = None
    return v if v is not None and 6 <= v <= 40 else None


def normalise(item, source):
    address = pick(item, "address.full", "address.display", "address")
    if isinstance(address, dict):
        address = _as_text(address)
    price_text = pick(item, "priceText", "price.display", "price")
    if isinstance(price_text, dict):
        price_text = _as_text(price_text)
    features_text = _as_text(pick(item, "propertyFeatures", "highlights", "features"))
    text = " \n".join(
        _as_text(pick(item, k)) for k in ("headline", "title", "description")
    ) + " \n" + features_text

    land_field = pick(item, "landSize", "landArea", "land.size", "landSizeSqm", "features.landSize")
    lot_field = extract.lot_from_field(land_field)
    lot_text = extract.lot_from_text(text)
    house_field = extract.house_squares_from_field(
        pick(item, "buildingSize", "buildingArea", "floorArea", "features.buildingSize")
    )
    house_text = extract.house_squares_from_text(text)
    frontage_field = pick(item, "frontage", "landFrontage", "features.frontage")
    frontage_text = extract.frontage_from_text(text)
    low, high = extract.parse_price(str(price_text or ""), pick(item, "priceFrom", "price.from"))
    ptype = pick(item, "propertyType")

    return {
        "source": source,
        "id": str(pick(item, "listingId", "propertyId", "id") or ""),
        "url": pick(item, "url", "listingUrl") or "",
        "address": address or "",
        "suburb": pick(item, "suburb", "address.suburb") or "",
        "property_type": ptype or "",
        "kind": extract.rough_kind(ptype, text),
        "construction": pick(item, "constructionStatus", "condition") or "",
        "price_text": price_text or "",
        "price_low": low,
        "price_high": high,
        "bedrooms": pick(item, "bedrooms", "features.bedrooms"),
        "bathrooms": pick(item, "bathrooms", "features.bathrooms"),
        "parking": pick(item, "parkingSpaces", "features.parkingSpaces"),
        "lot_m2_field": lot_field,
        "lot_m2_text": lot_text,
        "lot_m2": lot_field or lot_text,
        "frontage_m_field": _frontage_field(frontage_field),
        "frontage_m_text": frontage_text,
        "frontage_m": _frontage_field(frontage_field) or frontage_text,
        "house_sq_field": house_field,
        "house_sq_text": house_text,
        "house_sq": house_field or house_text,
        "text_chars": len(text.strip()),
    }
