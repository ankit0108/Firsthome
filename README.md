# First-home listing agent

Twice-daily email of new homes, house-and-land packages and titled land around Cranbourne and Clyde that fit first-home-buyer limits. Built in six gated chunks; this folder currently holds **chunk 1: source test**.

## Chunk 1: what it does

Runs two realestate.com.au scrapers on Clyde North (house and land, up to $750,000) and measures, for each:

- how many listings come back, and what kinds (land, package, house)
- how often price, lot size, frontage and house size can be read
- how many listings with a known value pass the new rules: frontage 12.5 m or more, house over 21 squares
- how many listings the two scrapers share

It also re-reads 40 listings with full listing-page details, to see whether details are worth paying for on new listings.

| File | Role |
| --- | --- |
| `config.py` | All thresholds: suburbs, price caps, lot, frontage, house size |
| `extract.py` | Reads price, lot size, frontage and house size from fields and ad text |
| `sources.py` | Calls Apify and maps both scrapers' rows to one shape |
| `chunk1_source_test.py` | Runs the test and writes the gate files |
| `tests/` | Unit tests for the extractors and mapping |

## Run it in GitHub Actions

1. Add your Apify token as a repo secret named `APIFY_TOKEN` (Settings, Secrets and variables, Actions, New repository secret).
2. Open the Actions tab, choose **Chunk 1 source test**, then **Run workflow**.
3. When it finishes, the summary shows on the run page, and `chunk1-results` under Artifacts holds `summary.md`, `listings.csv`, `hand_check.csv` and the raw scraper output.

## Run it on your own computer

1. **Python 3.10 or later.** Check with `python --version`.
2. **Apify account** on the Free plan, which includes US$5 of usage a month. Copy your API token from the Apify Console settings, then set it in your terminal (never in a file you commit):
   - macOS or Linux: `export APIFY_TOKEN=your_token`
   - Windows PowerShell: `$env:APIFY_TOKEN="your_token"`
3. **Install and test:**
   ```
   python -m pip install -r requirements.txt
   python -m unittest discover -s tests
   ```
4. **Run:** `python chunk1_source_test.py`. It takes about 5-15 minutes and prints progress.
5. **Re-analyse without paying again:** `python chunk1_source_test.py --from-cache`

## Cost

At most about US$1.40, inside the free US$5: scraper A list mode capped at 800 rows (US$0.54), the 40-listing details re-read (about US$0.11), and scraper B capped at 300 rows (about US$0.72 on the Free plan). Each run also carries a spend cap.

## Known limits on the Free plan

- **Scraper B runs in reduced mode.** Its page says Free plans have no residential proxy, so it falls back to a backup connection and leaves out listing links, images and agent details. Its counts and fill rates still compare fairly; its link column will be blank.
- **If the details re-read fails**, re-run with `--detail-sample 0` and tell me. Scraper A's docs don't show the exact format for listing-URL input, so that step may need one adjustment.

## Gate: check before chunk 2

Results land in `out/`: `summary.md`, `listings.csv` and `hand_check.csv`.

- [ ] **Accuracy:** in `hand_check.csv`, open each of the 20 links and fill the `site_` columns and `match_y_n`. Pass: 18 of 20 or better on price and listing kind.
- [ ] **Coverage:** search realestate.com.au yourself with the same filters. Pass: the site's count is within about 10% of scraper A's rows.
- [ ] **Fill rates:** read them in `summary.md`. They decide how much chunk 2 relies on AI reading of ad text.
- [ ] **Packages:** spot-check 5 package ads for frontage and house size. Where an ad doesn't state them, that listing will go to the flagged section.

Then paste `summary.md` and your hand-check score into the chat. Don't paste your token.
