"""Search rules for the first-home listing agent (see the PRD, "Search rules").

Every module reads its thresholds from here, so a rule changes in one place.
"""

SUBURBS = [
    # (suburb, state, postcode)
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
DUTY_FREE_UP_TO = 600_000  # first home buyer: no duty up to this value

# Lot size (m²): strict limits, no near-miss band
LOT_MIN, LOT_MAX = 300, 400
LOT_NEAR_MIN, LOT_NEAR_MAX = LOT_MIN, LOT_MAX  # kept for chunk 1's report

# Double garage: houses and packages need 2+ garage spaces.
# Titled land needs 12.5 m frontage; 10.5-12.4 m is a near miss.
GARAGE_MIN = 2
FRONTAGE_MIN = 12.5
FRONTAGE_NEAR_MIN = 10.5

# House size: 21 squares or more, read from the advertised total area
SQ_M_PER_SQUARE = 9.290304  # 1 square = 100 sq ft
HOUSE_MIN_SQUARES = 21.0

# Search (one scraper run covers every suburb)
EXCLUDE_STATUSES = ["under-contract", "deposit-taken"]
MAX_RESULTS = 2000
MAX_RESULTS_PER_SUBURB = 400
RUN_CHARGE_CAP_USD = 1.00

# AI tagging
AI_MODEL = "claude-haiku-5-5"
AI_WORKERS = 4

# Schedule: GitHub starts the job at 7am and 6pm in both AEDT and AEST (UTC crons),
# and the agent sends once per window, so daylight saving and late starts are handled.
TIMEZONE = "Australia/Melbourne"
SLOTS = {"morning": (6 * 60 + 30, 10 * 60), "evening": (17 * 60 + 30, 21 * 60)}  # minutes after midnight
SLOT_LABEL = {"morning": "7am", "evening": "6pm"}

# Report
MAX_PER_SECTION = 60
