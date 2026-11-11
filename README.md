# First-home listing agent

Emails a report at 7am and 6pm Melbourne time listing brand-new houses, house-and-land packages and titled land in Clyde North, Clyde, Cranbourne (all five), and Junction Village that fit first-home-buyer limits.

## Rules

| Rule | Limit |
| --- | --- |
| Price | Houses and packages up to $750,000; titled land up to $400,000 |
| Lot size | 300-400 m² |
| House size | 21 squares or more (advertised total) |
| Double garage | Houses and packages: 2+ garage spaces. Land: frontage 12.5 m or more |
| Brand new | Never lived in; established homes and townhouses are left out |
| Status | Under contract and deposit taken are left out |

Each listing lands in one section of the report:

- **Matches:** passes every rule.
- **Near misses:** a price range running over the cap, or land with 10.5-12.4 m frontage.
- **To check:** the ad doesn't state something a rule needs (price, lot size, house size, garage, frontage, titled status).
- Anything that breaks a rule is left out.

All limits live in `config.py`.

## Set up (once)

Add these repo secrets under Settings, Secrets and variables, Actions:

| Secret | What it is |
| --- | --- |
| `APIFY_TOKEN` | Apify API token (already added) |
| `GMAIL_ADDRESS` | The Gmail account that sends the report |
| `GMAIL_APP_PASSWORD` | A Gmail app password for that account (needs 2-Step Verification) |
| `REPORT_RECIPIENTS` | Comma-separated email addresses that get the report |
| `ANTHROPIC_API_KEY` | Optional. Lets Claude read each ad for type, titled status, sizes and garage. Without it, rules read the ad text instead, which catches less |

Without the three Gmail secrets the agent still runs, but sends nothing and saves nothing.

## Run

- **Scheduled:** runs itself twice a day. GitHub starts it at 7am and 6pm in both AEDT and AEST, and the agent sends once per window.
- **By hand:** Actions tab, **Home listing agent**, **Run workflow**. Tick "dry run" to build the report without emailing or saving state.
- **Results:** the run page shows a summary; the `report` artifact holds the full HTML report.
- **On your computer:** `python agent.py --dry-run` with the secrets set as environment variables.

New, price-changed and removed listings are worked out against `state/state.json`, which each successful run commits back to the repo. A failed run emails the error to `GMAIL_ADDRESS`.

## Cost

About US$0.27 of Apify usage per Clyde North sweep in testing; the site-side filters (price, 300-400 m², status) keep the full sweep small. Each run is capped at US$1. AI tagging reads each listing once and again only when its ad changes, at well under US$1 a month.

## Files

| File | Role |
| --- | --- |
| `agent.py` | Runs everything: schedule check, fetch, tag, sort, compare, report, email, save state |
| `config.py` | Every limit and setting |
| `sources.py` | Calls the Apify scraper and maps its rows to one shape |
| `tagger.py` | Claude tagging, cached per listing, with a rule-based fallback |
| `extract.py` | Reads price, sizes, frontage and garage from fields and ad text |
| `rules.py` | Sorts each listing into a section, with reasons and duty and grant notes |
| `report.py` | Builds the email and sends it through Gmail |
| `chunk1_source_test.py` | The original source test, kept for re-checking the scraper |
| `tests/` | Unit and end-to-end tests: `python -m unittest discover -s tests` |

Duty and grant notes in the report are estimates. Confirm them with a conveyancer or the SRO calculator before acting.
