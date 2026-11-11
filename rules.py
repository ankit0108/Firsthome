"""Sort each listing into a report section, with the reasons.

Sections, strictest first: excluded, near_miss, flagged, main. A listing lands
in the strictest section any rule gives it, and keeps every reason.
"""
import config

TYPE_LABEL = {
    "house_and_land_package": "House and land package",
    "new_house": "New house",
    "land": "Titled land",
    "house_unclear": "House (new or not unclear)",
    "established_house": "Established house",
    "townhouse": "Townhouse",
    "other": "Other",
}


def _num(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(*values):
    for v in values:
        n = _num(v)
        if n is not None:
            return n
    return None


def merge(row, tags):
    """One record per listing: structured fields first for lot size, AI tags next, ad-text patterns last."""
    t = tags or {}
    listing_type = t.get("listing_type") if t.get("listing_type") in TYPE_LABEL else "other"
    return {
        "id": row["id"],
        "url": row.get("url", ""),
        "address": row.get("address", ""),
        "suburb": row.get("suburb", ""),
        "type": listing_type,
        "never_lived_in": t.get("never_lived_in"),
        "titled": t.get("titled"),
        "title_expected": t.get("title_expected"),
        "price_text": row.get("price_text", ""),
        "price_low": row.get("price_low"),
        "price_high": row.get("price_high"),
        "lot_m2": _first(row.get("lot_m2_field"), t.get("lot_m2"), row.get("lot_m2_text")),
        "frontage_m": _first(t.get("frontage_m"), row.get("frontage_m")),
        "house_sq": _first(t.get("house_squares"), row.get("house_sq_field"), row.get("house_sq_text")),
        "garage": _first(t.get("garage_spaces"), row.get("parking")),
        "bedrooms": row.get("bedrooms"),
        "bathrooms": row.get("bathrooms"),
        "separate_contracts": t.get("separate_contracts"),
        "land_price": _num(t.get("land_price")),
    }


def classify(m):
    """Return (section, reasons) for one merged listing."""
    excluded, near, flagged = [], [], []
    kind = m["type"]
    land = kind == "land"

    if kind in ("established_house", "townhouse", "other"):
        excluded.append(TYPE_LABEL[kind].lower())
    elif kind == "house_unclear":
        flagged.append("not clear it's brand new")
    if m.get("never_lived_in") is False and not land:
        excluded.append("not brand new")

    cap = config.CAP_TITLED_LAND if land else config.CAP_HOUSE_OR_PACKAGE
    low, high = m.get("price_low"), m.get("price_high")
    if low is None:
        flagged.append("no price shown")
    elif low > cap:
        excluded.append(f"price over ${cap:,}")
    elif high is not None and high > cap:
        near.append(f"price range runs to ${high:,.0f}")

    lot = m.get("lot_m2")
    if lot is None:
        flagged.append("no land size shown")
    elif not config.LOT_MIN <= lot <= config.LOT_MAX:
        excluded.append(f"lot {lot:,.0f} m², outside {config.LOT_MIN}-{config.LOT_MAX}")

    if land:
        front = m.get("frontage_m")
        if front is None:
            flagged.append("frontage not stated: check the lot plan")
        elif front < config.FRONTAGE_NEAR_MIN:
            excluded.append(f"frontage {front:g} m, too narrow for a double garage")
        elif front < config.FRONTAGE_MIN:
            near.append(f"frontage {front:g} m: double garage possible but tight")
        titled = m.get("titled")
        if titled == "titling_soon":
            flagged.append(f"titles expected {m.get('title_expected') or 'soon'}")
        elif titled == "untitled":
            excluded.append("not titled yet" + (f" (expected {m['title_expected']})" if m.get("title_expected") else ""))
        elif titled is None:
            flagged.append("titled status not stated")
    else:
        sq = m.get("house_sq")
        if sq is None:
            flagged.append("house size not stated")
        elif sq < config.HOUSE_MIN_SQUARES:
            excluded.append(f"house {sq:g} squares, under {config.HOUSE_MIN_SQUARES:g}")
        garage = m.get("garage")
        if garage is None:
            flagged.append("garage not stated")
        elif garage < config.GARAGE_MIN:
            excluded.append("single garage")

    if excluded:
        return "excluded", excluded + near + flagged
    if near:
        return "near_miss", near + flagged
    if flagged:
        return "flagged", flagged
    return "main", []


def money_notes(m):
    """Short duty and grant notes. Estimates only: the report says to confirm them."""
    kind = m["type"]
    price = m.get("price_high") or m.get("price_low")
    if price is None:
        return "Duty: price not shown", ""
    free, cap = config.DUTY_FREE_UP_TO, config.CAP_HOUSE_OR_PACKAGE

    def band(value):
        if value <= free:
            return "no duty"
        return "reduced duty" if value <= cap else "full duty"

    if kind == "land":
        left = cap - price
        return f"Duty: {band(price)}", f"Build budget left ${left:,.0f} for the $10k grant"
    if kind == "house_and_land_package":
        if m.get("separate_contracts") and m.get("land_price"):
            duty = f"Duty on land only: {band(m['land_price'])}"
        elif m.get("separate_contracts") is False:
            duty = f"Duty on full price: {band(price)}"
        else:
            duty = "Duty: on land only if separate contracts"
        return duty, "$10k grant likely" if price <= cap else "Over grant cap"
    return f"Duty: {band(price)}", "$10k grant likely" if price <= cap else "Over grant cap"
