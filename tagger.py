"""Tag each listing once with Claude: type, brand new or not, titled, sizes, garage.

Tags are cached by listing id and ad-text hash, so a listing is re-read only
when its ad changes. Without ANTHROPIC_API_KEY, or when a call fails, the
listing gets rule-based tags instead and is retried with AI on the next run.
"""
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import extract

API = "https://api.anthropic.com/v1/messages"
TYPES = {"house_and_land_package", "new_house", "established_house", "land", "townhouse", "other"}

SYSTEM = """You read Australian property listings for a first-home buyer and return facts as JSON.
Return only one JSON object, no other text, with exactly these keys:
- listing_type: "house_and_land_package" (a house to be built or being built, sold with its lot), "new_house" (completed and never lived in), "established_house" (previously lived in, including "1 year old"), "land" (vacant lot only), "townhouse", or "other"
- never_lived_in: true, false, or null
- titled: "titled" (titles issued, ready to build), "titling_soon" (titles expected within about 3 months), "untitled" (later than that), or null
- title_expected: when titles are expected, as written in the ad (e.g. "March 2027"), or null
- lot_m2: lot size in square metres, or null
- frontage_m: lot frontage (width at the street) in metres, or null. For "12.5 x 28m" the frontage is 12.5.
- house_squares: total house area in squares (1 square = 9.29 m²; convert m² by dividing by 9.29), or null
- garage_spaces: number of garage spaces (not carports, driveway or open spaces), or null
- separate_contracts: true if land and build are sold on separate contracts, false if one contract, or null
- land_price: land price in AUD for a package, if stated separately, or null
Use null whenever the ad doesn't say. Never guess."""


def text_hash(row):
    raw = (row.get("price_text") or "") + "\n" + (row.get("text") or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def rule_tags(row):
    """Tags from patterns in the ad text, used when AI tagging isn't available."""
    text = row.get("text") or ""
    probe = (row.get("price_text") or "") + "\n" + text
    kind = row.get("kind")
    construction = str(row.get("construction") or "").lower()
    used = bool(extract.USED.search(probe)) or construction == "established"
    new = bool(extract.NEW_BUILD.search(probe)) or construction == "new"
    if kind == "land":
        listing_type = "land"
    elif kind == "townhouse":
        listing_type = "townhouse"
    elif kind == "package":
        listing_type = "house_and_land_package"
    elif kind == "house":
        listing_type = "established_house" if used and not new else "new_house" if new else "house_unclear"
    else:
        listing_type = "other"
    titled = "titled" if extract.TITLED.search(text) else "titling_soon" if extract.TITLING.search(text) else None
    return {
        "listing_type": listing_type,
        "never_lived_in": False if used else True if new else None,
        "titled": titled,
        "title_expected": None,
        "lot_m2": None,
        "frontage_m": None,
        "house_squares": None,
        "garage_spaces": extract.garage_from_text(text),
        "separate_contracts": None,
        "land_price": None,
    }


def ai_tags(row, key, attempts=3):
    content = (
        f"Price: {row.get('price_text') or 'not shown'}\n"
        f"Type on site: {row.get('property_type') or 'unknown'}\n"
        f"Address: {row.get('address') or 'not shown'}\n\n"
        f"{(row.get('text') or '')[:8000]}"
    )
    for attempt in range(attempts):
        r = requests.post(
            API,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": config.AI_MODEL,
                "max_tokens": 400,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=90,
        )
        if r.status_code in (429, 500, 529) and attempt < attempts - 1:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    reply = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise ValueError("no JSON in the reply")
    tags = json.loads(m.group(0))
    if tags.get("listing_type") not in TYPES:
        raise ValueError(f"unexpected listing_type {tags.get('listing_type')!r}")
    return tags


def tag_all(rows, cache):
    """Return (tags by listing id, new cache, counts). The cache keeps only current listings."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    tags, new_cache, todo = {}, {}, []
    stats = {"ai": 0, "rules": 0, "cached": 0, "ai_failed": 0}
    for row in rows:
        h = text_hash(row)
        hit = cache.get(row["id"])
        if hit and hit.get("hash") == h and (hit.get("by") == "ai" or not key):
            tags[row["id"]] = hit["tags"]
            new_cache[row["id"]] = hit
            stats["cached"] += 1
        else:
            todo.append((row, h))

    def work(item):
        row, h = item
        if key:
            try:
                return row, h, ai_tags(row, key), "ai"
            except Exception as e:  # noqa: BLE001 - any failure falls back to rules
                print(f"  AI tagging failed for {row['id']}: {e}")
                return row, h, rule_tags(row), "ai_failed"
        return row, h, rule_tags(row), "rules"

    with ThreadPoolExecutor(max_workers=config.AI_WORKERS) as pool:
        for row, h, t, by in pool.map(work, todo):
            tags[row["id"]] = t
            new_cache[row["id"]] = {"hash": h, "by": "ai" if by == "ai" else "rules", "tags": t}
            stats[by] += 1
    return tags, new_cache, stats
