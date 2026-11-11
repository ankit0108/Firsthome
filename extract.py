"""Read price, lot size, frontage and house size from listing fields and ad text.

Chunk 1 uses these to measure how often each value is available.
Chunk 2 adds AI extraction; these stay as a cheap cross-check.
Every function returns None when it can't find a plausible value.
"""
import re

from config import SQ_M_PER_SQUARE

_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_SMALL = r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})?)"
_AREA_UNIT = r"(?:m2|m²|sqm|sq\.?\s?m(?:etres?|eters?)?|square\s+met(?:re|er)s?)(?![a-z])"
_LOT_WORDS = r"(?:land|lot|block|allotment|site)"
_FILLER = r"(?:\s|of|:|-|–|is|approx\.?|approximately|~|circa|size|area)*"


def _num(s):
    return float(s.replace(",", ""))


# ---------- price ----------

_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(k|m|mil(?:lion)?)?\b", re.I)


def parse_price(text, price_from=None):
    """Return (low, high) in AUD, or (None, None) for 'Contact agent' and the like."""
    if isinstance(price_from, (int, float)) and price_from > 50_000:
        low = float(price_from)
    else:
        low = None
    values = []
    for amount, suffix in _MONEY.findall(text or ""):
        v = _num(amount)
        s = (suffix or "").lower()
        if s == "k":
            v *= 1_000
        elif s.startswith("m"):
            v *= 1_000_000
        if v >= 50_000:
            values.append(v)
    if values:
        return (min(values), max(values))
    return (low, low)


# ---------- lot size ----------

_LOT_PATTERNS = [
    re.compile(_LOT_WORDS + _FILLER + _NUM + r"\s?" + _AREA_UNIT, re.I),
    re.compile(_NUM + r"\s?" + _AREA_UNIT + r"\s*(?:\(approx\.?\)\s*)?(?:corner\s+|level\s+|flat\s+)?" + _LOT_WORDS, re.I),
]
_HECTARE = re.compile(_NUM + r"\s?(?:ha|hectares?)\b", re.I)


def lot_from_field(value):
    """Normalise a structured land-size field: 350, '350m²', {'value': 350, 'unit': 'm2'}."""
    if value is None:
        return None
    if isinstance(value, dict):
        v = value.get("value") or value.get("size") or value.get("area")
        unit = str(value.get("unit") or value.get("units") or "m2")
        return lot_from_field(f"{v} {unit}") if v is not None else None
    if isinstance(value, (int, float)):
        return float(value) if 100 <= value <= 100_000 else None
    s = str(value)
    m = _HECTARE.search(s)
    if m:
        return _num(m.group(1)) * 10_000
    m = re.search(_NUM, s)
    if not m:
        return None
    v = _num(m.group(1))
    if re.search(r"acre", s, re.I):
        v *= 4046.86
    return v if 100 <= v <= 100_000 else None


def lot_from_text(text):
    for pattern in _LOT_PATTERNS:
        for m in pattern.finditer(text or ""):
            v = _num(m.group(1))
            if 150 <= v <= 2_000:
                return v
    return None


# ---------- frontage ----------

_FRONTAGE_PATTERNS = [
    re.compile(_SMALL + r"\s?m(?:etres?|eters?|trs?)?\.?\s*(?:wide\s*)?frontage", re.I),
    re.compile(r"frontage" + _FILLER + _SMALL + r"\s?m(?![a-z²2])", re.I),
    re.compile(_SMALL + r"\s?m(?:etres?|eters?)?\s+wide\s+(?:block|lot|land|allotment|frontage)", re.I),
]
_DIMENSIONS = re.compile(_SMALL + r"\s?m?\s?[x×]\s?(\d{2}(?:\.\d{1,2})?)\s?m(?![a-z²2])", re.I)


def frontage_from_text(text):
    for pattern in _FRONTAGE_PATTERNS:
        for m in pattern.finditer(text or ""):
            v = float(m.group(1))
            if 6 <= v <= 40:
                return v
    for m in _DIMENSIONS.finditer(text or ""):
        width, depth = float(m.group(1)), float(m.group(2))
        if 6 <= width <= 25 and 15 <= depth <= 60 and width < depth:
            return width
    return None


# ---------- house size (in squares) ----------

_SQUARES = re.compile(
    r"(?<![\d.])(\d{2}(?:\.\d{1,2})?)\s?(?:squares?(?!\s*met)|sqs|sq(?![\s.]*m))(?![a-z])", re.I
)
_HOUSE_M2 = re.compile(
    r"(?:house|home|build(?:ing)?|living|floor|internal|total)" + _FILLER + _NUM + r"\s?" + _AREA_UNIT, re.I
)


def house_squares_from_field(value):
    """Normalise a structured building-size field to squares."""
    m2 = lot_from_field(value)
    if m2 is None:
        return None
    sq = m2 / SQ_M_PER_SQUARE
    return round(sq, 1) if 8 <= sq <= 70 else None


def house_squares_from_text(text):
    for m in _SQUARES.finditer(text or ""):
        v = float(m.group(1))
        if 10 <= v <= 70:
            return v
    for m in _HOUSE_M2.finditer(text or ""):
        v = _num(m.group(1))
        if 80 <= v <= 650:
            return round(v / SQ_M_PER_SQUARE, 1)
    return None


# ---------- garage, new build, titled (rule-based fallback for the AI tags) ----------

_GARAGE = [
    (re.compile(r"garage\s+spaces?\s*:?\s*(\d)", re.I), None),
    (re.compile(r"\b(?:triple|three[\s-]?car|3[\s-]?car)[\s-]+(?:car\s+)?(?:lock[\s-]?up\s+|remote\s+|auto\s+)?garag", re.I), 3),
    (re.compile(r"\b(?:double|two[\s-]?car|2[\s-]?car)[\s-]+(?:car\s+)?(?:lock[\s-]?up\s+|remote\s+|auto\s+)?garag", re.I), 2),
    (re.compile(r"\b(?:single|one[\s-]?car|1[\s-]?car)[\s-]+(?:car\s+)?(?:lock[\s-]?up\s+|remote\s+|auto\s+)?garag", re.I), 1),
]

NEW_BUILD = re.compile(
    r"brand[\s-]?new|never\s+(?:been\s+)?lived\s+in|newly\s+(?:built|completed)|just\s+completed"
    r"|turn[\s-]?key|move[\s-]in\s+ready|house\s*(?:&|and)\s*land|fixed\s+price", re.I)
USED = re.compile(
    r"\b\d+\s*(?:years?|yrs?)\s*old\b|\btenanted\b|currently\s+leased|previously\s+(?:occupied|lived)", re.I)
TITLED = re.compile(
    r"\btitled\b(?!\s+(?:expected|due|in\s+20))|titles?\s+(?:are\s+)?(?:now\s+)?(?:issued|registered)"
    r"|ready\s+to\s+build", re.I)
TITLING = re.compile(
    r"titles?\s+(?:are\s+)?(?:expected|due|anticipated)|titling|expected\s+titles?|\buntitled\b|pre[\s-]?title", re.I)


def garage_from_text(text):
    for pattern, n in _GARAGE:
        m = pattern.search(text or "")
        if m:
            return int(m.group(1)) if n is None else n
    return None


# ---------- listing kind (rough; the AI tags replace this when available) ----------

_PACKAGE = re.compile(r"house\s*(?:&|and|\+|n)\s*land|\bh\s?&\s?l\b|\bpackage\b|turn\s?key", re.I)


def rough_kind(property_type, text):
    t = (property_type or "").lower()
    if "town" in t:
        return "townhouse"
    if "land" in t and "house" not in t:
        return "land"
    if _PACKAGE.search(text or ""):
        return "package"
    if "house" in t or "home" in t:
        return "house"
    return t or "unknown"
