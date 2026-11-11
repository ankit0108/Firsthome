"""Search rules for the first-home listing agent (see the PRD, "Search rules").

Every later chunk reads its thresholds from here, so a rule changes in one place.
"""

SUBURBS = [
    # (suburb, state, postcode). Chunk 1 tests Clyde North only.
    ("Clyde North", "VIC", "3978"),
    ("Clyde", "VIC", "3978"),
    ("Cranbourne", "VIC", "3977"),
    ("Cranbourne East", "VIC", "3977"),
    ("Cranbourne North", "VIC", "3977"),
    ("Cranbourne South", "VIC", "3977"),
    ("Cranbourne West", "VIC", "3977"),
    ("Junction Village", "VIC", "3977"),
]

# Price caps (AUD)
CAP_HOUSE_OR_PACKAGE = 750_000
CAP_TITLED_LAND = 400_000

# Lot size (m²): main list, then the near-miss band either side
LOT_MIN, LOT_MAX = 300, 400
LOT_NEAR_MIN, LOT_NEAR_MAX = 280, 420

# Frontage (m): 12.5 m fits a standard double garage; 10.5-12.4 m is a near miss
FRONTAGE_MIN = 12.5
FRONTAGE_NEAR_MIN = 10.5

# House size: more than 21 squares, read from the advertised total area
SQ_M_PER_SQUARE = 9.290304  # 1 square = 100 sq ft
HOUSE_MIN_SQUARES = 21.0  # strictly greater than this
