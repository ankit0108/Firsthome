"""Chunk 1: source test.

Runs both candidate scrapers on one suburb, then measures what each returns:
rows, listing kinds, and how often price, lot size, frontage and house size
are available. Writes the files you check at the gate.

    python chunk1_source_test.py                # live run, about US$1-2 of Apify usage
    python chunk1_source_test.py --from-cache   # re-analyse saved results, no cost
"""
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import config
import sources

FIELDS = [
    "source", "id", "url", "address", "suburb", "property_type", "kind", "construction",
    "price_text", "price_low", "price_high", "bedrooms", "bathrooms", "parking",
    "lot_m2_field", "lot_m2_text", "lot_m2", "frontage_m_field", "frontage_m_text",
    "frontage_m", "house_sq_field", "house_sq_text", "house_sq", "text_chars",
]


def pct(n, d):
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a (0 rows)"


def address_key(address):
    a = (address or "").lower()
    if not re.search(r"\d", a):
        return None  # "Address available on request" and similar can't be matched
    a = re.sub(r"\b(vic|victoria|nsw)\b|\b\d{4}\b", " ", a)
    a = re.sub(r"[^a-z0-9/ ]", " ", a)
    for long, short in [("street", "st"), ("road", "rd"), ("avenue", "ave"), ("drive", "dr"),
                        ("court", "ct"), ("crescent", "cres"), ("boulevard", "blvd"),
                        ("parade", "pde"), ("place", "pl"), ("circuit", "cct"), ("way", "wy")]:
        a = re.sub(rf"\b{long}\b", short, a)
    return " ".join(a.split())


def fill_stats(rows):
    n = len(rows)
    builds = [r for r in rows if r["kind"] in ("house", "package")]
    lands = [r for r in rows if r["kind"] == "land"]
    out = {
        "rows": n,
        "kinds": dict(Counter(r["kind"] for r in rows).most_common()),
        "price": pct(sum(r["price_low"] is not None for r in rows), n),
        "lot_field": pct(sum(r["lot_m2_field"] is not None for r in rows), n),
        "lot_any": pct(sum(r["lot_m2"] is not None for r in rows), n),
        "frontage_any": pct(sum(r["frontage_m"] is not None for r in rows), n),
        "frontage_land": pct(sum(r["frontage_m"] is not None for r in lands), len(lands)),
        "house_any": pct(sum(r["house_sq"] is not None for r in builds), len(builds)),
        "text": pct(sum(r["text_chars"] > 200 for r in rows), n),
    }
    lots = [r["lot_m2"] for r in rows if r["lot_m2"] is not None]
    fronts = [r["frontage_m"] for r in rows if r["frontage_m"] is not None]
    houses = [r["house_sq"] for r in builds if r["house_sq"] is not None]
    out["lot_bands"] = {
        "300-400": sum(config.LOT_MIN <= v <= config.LOT_MAX for v in lots),
        "near miss": sum((config.LOT_NEAR_MIN <= v < config.LOT_MIN) or (config.LOT_MAX < v <= config.LOT_NEAR_MAX) for v in lots),
        "outside": sum(v < config.LOT_NEAR_MIN or v > config.LOT_NEAR_MAX for v in lots),
    }
    out["frontage_bands"] = {
        f">= {config.FRONTAGE_MIN} m": sum(v >= config.FRONTAGE_MIN for v in fronts),
        f"{config.FRONTAGE_NEAR_MIN} to under {config.FRONTAGE_MIN} m": sum(config.FRONTAGE_NEAR_MIN <= v < config.FRONTAGE_MIN for v in fronts),
        f"< {config.FRONTAGE_NEAR_MIN} m": sum(v < config.FRONTAGE_NEAR_MIN for v in fronts),
    }
    out["house_bands"] = {
        f"> {config.HOUSE_MIN_SQUARES:g} squares": sum(v > config.HOUSE_MIN_SQUARES for v in houses),
        f"<= {config.HOUSE_MIN_SQUARES:g} squares": sum(v <= config.HOUSE_MIN_SQUARES for v in houses),
    }
    return out


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def stats_block(name, s):
    lines = [
        f"### {name}", "",
        f"- Rows: {s['rows']}",
        f"- Kinds (rough, from type and ad text): {s['kinds']}",
        f"- Price parsed: {s['price']}",
        f"- Lot size from structured field: {s['lot_field']}",
        f"- Lot size from field or ad text: {s['lot_any']}",
        f"- Frontage from field or ad text: {s['frontage_any']} (land only: {s['frontage_land']})",
        f"- House size, houses and packages only: {s['house_any']}",
        f"- Rows with a usable description (over 200 characters): {s['text']}",
        f"- Lot bands, where known: {s['lot_bands']}",
        f"- Frontage bands, where known: {s['frontage_bands']}",
        f"- House size bands, where known: {s['house_bands']}",
        "",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suburb", default="Clyde North")
    p.add_argument("--state", default="VIC")
    p.add_argument("--postcode", default="3978")
    p.add_argument("--max-price", type=int, default=config.CAP_HOUSE_OR_PACKAGE)
    p.add_argument("--max-a", type=int, default=800, help="row cap for scraper A")
    p.add_argument("--max-b", type=int, default=300, help="row cap for scraper B")
    p.add_argument("--detail-sample", type=int, default=40, help="listings re-read with full details")
    p.add_argument("--skip-b", action="store_true", help="run scraper A only")
    p.add_argument("--from-cache", action="store_true", help="re-analyse saved raw results")
    p.add_argument("--out", default="out")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    runs = json.loads((out / "runs.json").read_text()) if args.from_cache and (out / "runs.json").exists() else {}

    def fetch(key, actor, run_input, cap_usd):
        raw_path = out / f"raw_{key}.json"
        if args.from_cache:
            return json.loads(raw_path.read_text()) if raw_path.exists() else None
        print(f"Running {key} ({actor}) ...")
        try:
            items, info = sources.run_actor(actor, run_input, max_charge_usd=cap_usd)
        except sources.ApifyError as e:
            print(f"  FAILED: {e}")
            runs[key] = {"actor": actor, "status": "FAILED", "error": str(e)}
            return None
        raw_path.write_text(json.dumps(items, indent=1))
        runs[key] = info
        print(f"  {len(items)} rows")
        return items

    loc = (args.suburb, args.state, args.postcode)
    raw_a = fetch("a", sources.SCRAPER_A, sources.input_a(*loc, args.max_price, args.max_a), 2.0)
    rows_a = [sources.normalise(i, "A") for i in raw_a or []]

    rows_ad = []
    if rows_a and args.detail_sample:
        rng = random.Random(7)
        with_url = [r for r in rows_a if r["url"]]
        sample = rng.sample(with_url, min(args.detail_sample, len(with_url)))
        raw_ad = fetch("a_details", sources.SCRAPER_A, sources.input_a_details([r["url"] for r in sample]), 1.0)
        rows_ad = [sources.normalise(i, "A+details") for i in raw_ad or []]

    rows_b = []
    if not args.skip_b:
        raw_b = fetch("b", sources.SCRAPER_B, sources.input_b(*loc, args.max_price, args.max_b), 2.0)
        rows_b = [sources.normalise(i, "B") for i in raw_b or []]

    if not args.from_cache:
        (out / "runs.json").write_text(json.dumps(runs, indent=1))

    if not (rows_a or rows_b):
        print("No rows from either scraper. See out/runs.json for the reason.")
        sys.exit(1)

    write_csv(out / "listings.csv", rows_a + rows_ad + rows_b, FIELDS)

    # Same listings, list mode vs details mode
    ad_ids = {r["id"] for r in rows_ad if r["id"]}
    a_matched = [r for r in rows_a if r["id"] in ad_ids]

    # Overlap between scrapers by address
    keys_a = {address_key(r["address"]) for r in rows_a} - {None}
    keys_b = {address_key(r["address"]) for r in rows_b} - {None}

    # Hand-check sheet: 20 random rows from A, blank columns for you to fill
    rng = random.Random(11)
    pool = [r for r in rows_a if r["url"]] or rows_a or rows_b
    check = rng.sample(pool, min(20, len(pool)))
    check_fields = ["url", "address", "kind", "price_text", "lot_m2", "frontage_m", "house_sq",
                    "site_price", "site_lot_m2", "site_frontage_m", "site_house_sq", "match_y_n", "notes"]
    write_csv(out / "hand_check.csv", check, check_fields)

    lines = [
        f"# Chunk 1 source test: {args.suburb} {args.postcode}", "",
        f"Filters: house and land, buy, up to ${args.max_price:,}, surrounding suburbs off.", "",
        "## Runs", "",
    ]
    for key, info in runs.items():
        lines.append(f"- **{key}** `{info.get('actor')}`: {info.get('status')}"
                     + (f", {info.get('seconds')} s" if info.get("seconds") else "")
                     + (f", usage US${info['usage_usd']:.3f}" if isinstance(info.get("usage_usd"), (int, float)) else "")
                     + (f". Error: {info['error']}" if info.get("error") else ""))
        if info.get("run_summary"):
            lines.append(f"  - Scraper's own run summary: `{json.dumps(info['run_summary'])[:600]}`")
    lines += ["", "## What each scraper returned", ""]
    if rows_a:
        lines.append(stats_block("Scraper A, list mode", fill_stats(rows_a)))
    if a_matched:
        lines.append(stats_block(f"Scraper A, same {len(a_matched)} listings, list mode", fill_stats(a_matched)))
    if rows_ad:
        lines.append(stats_block(f"Scraper A, same listings with full details", fill_stats(rows_ad)))
    if rows_b:
        lines.append(stats_block("Scraper B", fill_stats(rows_b)))
    if rows_a and rows_b:
        lines += [
            "## Overlap by street address", "",
            f"- Matched in both: {len(keys_a & keys_b)}",
            f"- Only in A: {len(keys_a - keys_b)}",
            f"- Only in B: {len(keys_b - keys_a)}",
            f"- Rows with no street address (not matchable): A {sum(address_key(r['address']) is None for r in rows_a)}, "
            f"B {sum(address_key(r['address']) is None for r in rows_b)}",
            "",
        ]
    lines += [
        "## Gate: you check these before chunk 2", "",
        "1. Open `hand_check.csv`. For each row, open the link and fill the `site_` columns and `match_y_n`. Pass: 18 of 20 or better on price and listing kind.",
        f"2. Search realestate.com.au yourself: {args.suburb}, house and land, up to ${args.max_price:,}, surrounding suburbs off. Pass: the site's result count is within about 10% of scraper A's rows (or the run summary above shows the site total).",
        "3. Look at the fill rates above. They decide how much chunk 2 leans on AI reading of ad text, and whether full details are worth paying for on new listings.",
        "4. Spot-check 5 package listings: does the ad give frontage and house size anywhere a buyer can see? If not, those listings will mostly land in the flagged section.",
        "",
    ]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out / 'summary.md'}, {out / 'listings.csv'}, {out / 'hand_check.csv'}")


if __name__ == "__main__":
    main()
