import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import report  # noqa: E402
import rules  # noqa: E402
import sources  # noqa: E402
import tagger  # noqa: E402

MEL = ZoneInfo("Australia/Melbourne")


def item(i, ptype, price, land=None, desc="", parking=None, suburb="Clyde North", address=None):
    """A scraper row shaped like scraper A's output."""
    return {
        "listingId": str(i), "url": f"https://www.realestate.com.au/x-{i}", "propertyType": ptype,
        "priceText": price, "address": address or f"{i} Test Street, {suburb}, Vic 3978", "suburb": suburb,
        "bedrooms": 4 if ptype != "Land" else None, "bathrooms": 2 if ptype != "Land" else None,
        "parkingSpaces": parking, "landSize": land, "description": desc,
    }


def tag(row_item):
    row = sources.normalise(row_item, "test")
    m = rules.merge(row, tagger.rule_tags(row))
    return m, rules.classify(m)


# Rows modelled on the Clyde North hand-check sample, plus listings that should pass.
SAMPLE = [
    item(1, "House", "$725,000 - Fixed Price & Full Turnkey Inclusions", "262m²", "House & land package, 17.8 squares, double garage"),
    item(2, "Land", "$560,000-$600,000", "456m²", "Titled land, 14m frontage"),
    item(3, "House", "$739,000-$799,000(1 Year Old Only)", "400m²", "Modern home, 24 squares, double garage"),
    item(4, "House", "$720,000", "350m²", "Brand new home, never lived in. 22 squares, double remote garage."),
    item(5, "Land", "$385,000", "350m²", "Titled and ready to build. 12.5m frontage."),
    item(6, "Land", "$370,000", "336m²", "Titled now. 11 x 30.5m block."),
    item(7, "House", "$699K-$758K! Brand New! $10k FHOG", "380m²", "Brand new, 23 squares, double garage"),
    item(8, "House", "Contact agent", "360m²", "Brand new home, 25 squares, 2 car garage"),
    item(9, "House", "$690,000", "320m²", "Brand new. Double garage."),
    item(10, "House", "$700,000", "375m²", "Brand new house & land package, 21 squares", parking=2),
    item(11, "House", "$700,000", "375m²", "Brand new, 24 squares, single car garage"),
    item(12, "Townhouse", "$600,000", "310m²", "Brand new townhouse, 21 squares, double garage"),
    item(13, "House", "$650,000", "350m²", "Brand new, 24 squares", suburb="Berwick"),
]


class Rules(unittest.TestCase):
    def section(self, i):
        return tag(SAMPLE[i - 1])[1][0]

    def test_small_lot_and_small_house_excluded(self):
        section, reasons = tag(SAMPLE[0])[1]
        self.assertEqual(section, "excluded")
        self.assertTrue(any("lot 262" in r for r in reasons))
        self.assertTrue(any("17.8 squares" in r for r in reasons))

    def test_land_over_cap_and_big_lot_excluded(self):
        self.assertEqual(self.section(2), "excluded")

    def test_one_year_old_excluded(self):
        self.assertEqual(self.section(3), "excluded")

    def test_full_match(self):
        self.assertEqual(self.section(4), "main")
        self.assertEqual(self.section(5), "main")

    def test_twenty_one_squares_is_enough(self):
        self.assertEqual(self.section(10), "main")

    def test_narrow_land_is_near_miss(self):
        m, (section, reasons) = tag(SAMPLE[5])
        self.assertEqual((section, m["frontage_m"]), ("near_miss", 11))

    def test_price_range_over_cap_is_near_miss(self):
        self.assertEqual(self.section(7), "near_miss")

    def test_missing_details_are_flagged(self):
        self.assertEqual(self.section(8), "flagged")  # no price
        section, reasons = tag(SAMPLE[8])[1]
        self.assertEqual(section, "flagged")
        self.assertIn("house size not stated", reasons)

    def test_single_garage_and_townhouse_excluded(self):
        self.assertEqual(self.section(11), "excluded")
        self.assertEqual(self.section(12), "excluded")

    def test_help_to_buy_price_is_flagged(self):
        section, reasons = tag(item(20, "House", "$486,176 - HTBS", "396m²", "Brand new, 22 squares, double garage"))[1]
        self.assertEqual(section, "flagged")
        self.assertTrue(any("Help to Buy" in r for r in reasons))

    def test_money_notes(self):
        m, _ = tag(SAMPLE[4])
        self.assertEqual(rules.money_notes(m), ("Duty: no duty", "Build budget left $365,000 for the $10k grant"))
        m, _ = tag(SAMPLE[3])
        self.assertEqual(rules.money_notes(m), ("Duty: reduced duty", "$10k grant likely"))


class Tagging(unittest.TestCase):
    def test_ai_tags_parsed_and_cached(self):
        row = sources.normalise(SAMPLE[3], "test")
        reply = {"content": [{"type": "text", "text": json.dumps({
            "listing_type": "new_house", "never_lived_in": True, "titled": None, "title_expected": None,
            "lot_m2": 350, "frontage_m": 12.5, "house_squares": 22, "garage_spaces": 2,
            "separate_contracts": None, "land_price": None})}]}
        fake = mock.Mock(status_code=200)
        fake.json.return_value = reply
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch("tagger.requests.post", return_value=fake) as post:
            tags, cache, stats = tagger.tag_all([row], {})
            self.assertEqual((tags[row["id"]]["frontage_m"], stats["ai"]), (12.5, 1))
            body = post.call_args.kwargs["json"]
            self.assertGreaterEqual(body["max_tokens"], 2000)  # room for Haiku 5.5's default thinking
            self.assertEqual(body["output_config"], {"effort": "low"})
            tags, cache, stats = tagger.tag_all([row], cache)
            self.assertEqual((stats["cached"], post.call_count), (1, 1))

    def test_ai_failure_falls_back_to_rules(self):
        row = sources.normalise(SAMPLE[3], "test")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch("tagger.requests.post", side_effect=RuntimeError("down")):
            tags, cache, stats = tagger.tag_all([row], {})
        self.assertEqual((stats["ai_failed"], tags[row["id"]]["listing_type"]), (1, "new_house"))
        self.assertEqual(cache[row["id"]]["by"], "rules")


class Schedule(unittest.TestCase):
    def test_windows_in_both_daylight_saving_states(self):
        utc = dt.timezone.utc
        cases = [
            ("2026-11-11T20:00", "morning"),  # 7am AEDT
            ("2026-11-11T21:00", "morning"),  # 8am AEDT: same window, deduplicated by state
            ("2026-11-11T07:00", "evening"),  # 6pm AEDT
            ("2026-06-11T20:00", None),       # 6am AEST: too early
            ("2026-06-11T21:00", "morning"),  # 7am AEST
            ("2026-06-11T08:00", "evening"),  # 6pm AEST
        ]
        for when, expected in cases:
            now = dt.datetime.fromisoformat(when).replace(tzinfo=utc).astimezone(MEL)
            self.assertEqual(agent.slot_for(now), expected, when)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.raw = self.dir / "raw.json"
        self.raw.write_text(json.dumps(SAMPLE))
        self.args = ["--raw", str(self.raw), "--state", str(self.dir / "state.json"), "--out", str(self.dir / "out")]
        self.env = {"GMAIL_ADDRESS": "me@example.com", "GMAIL_APP_PASSWORD": "abcd efgh",
                    "REPORT_RECIPIENTS": "a@example.com, b@example.com", "ANTHROPIC_API_KEY": "",
                    "GITHUB_EVENT_NAME": "schedule", "DRY_RUN": ""}

    def run_agent(self, when, raw=None):
        if raw is not None:
            self.raw.write_text(json.dumps(raw))
        with mock.patch.dict(os.environ, self.env), mock.patch("report.smtplib.SMTP_SSL") as smtp:
            code = agent.main(self.args + ["--now", when])
        sent = [c.args[0] for c in smtp.return_value.__enter__.return_value.send_message.call_args_list]
        return code, sent

    def test_first_run_then_changes(self):
        code, sent = self.run_agent("2026-11-11T07:05:00+11:00")
        self.assertEqual((code, len(sent)), (0, 1))
        self.assertIn("first report", sent[0]["Subject"])
        self.assertEqual(sent[0]["To"], "a@example.com, b@example.com")
        html_body = sent[0].get_body(("html",)).get_content()
        self.assertIn("7 Test Street", html_body)       # near miss shown
        self.assertNotIn('/x-1"', html_body)            # 262 m² lot excluded
        self.assertNotIn("Berwick", html_body)          # suburb outside the target list
        state = json.loads((self.dir / "state.json").read_text())
        self.assertEqual(state["last_sent"], {"date": "2026-11-11", "slot": "morning"})

        # Same window again: skipped, nothing sent
        code, sent = self.run_agent("2026-11-11T08:05:00+11:00")
        self.assertEqual((code, len(sent)), (0, 0))

        # Evening: one new listing, one price drop, one removed
        later = [dict(x) for x in SAMPLE if x["listingId"] != "5"]
        later = [dict(x, priceText="$705,000") if x["listingId"] == "4" else x for x in later]
        later.append(item(14, "House", "$710,000", "390m²", "Brand new, 23 squares, double garage"))
        code, sent = self.run_agent("2026-11-11T18:02:00+11:00", raw=later)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["Subject"], "Home search: 1 new, 1 price change (Wed 6pm)")
        text = sent[0].get_body(("plain",)).get_content()
        self.assertIn("Was: $720,000", text)
        self.assertIn("REMOVED SINCE LAST REPORT (1)", text)

    def test_outside_window_does_nothing(self):
        code, sent = self.run_agent("2026-11-11T13:00:00+11:00")
        self.assertEqual((code, len(sent)), (0, 0))
        self.assertFalse((self.dir / "state.json").exists())

    def test_no_email_secrets_means_no_state_change(self):
        self.env.update(GMAIL_APP_PASSWORD="", GITHUB_EVENT_NAME="workflow_dispatch")
        code, sent = self.run_agent("2026-11-11T13:00:00+11:00")
        self.assertEqual((code, len(sent)), (0, 0))
        self.assertTrue((self.dir / "out" / "report.html").exists())
        self.assertFalse((self.dir / "state.json").exists())

    def test_failure_sends_error_email_to_sender_only(self):
        self.raw.write_text("[]")
        self.env.update(GITHUB_EVENT_NAME="workflow_dispatch")
        with mock.patch.dict(os.environ, self.env), mock.patch("report.smtplib.SMTP_SSL") as smtp:
            code = agent.main(self.args)
        sent = [c.args[0] for c in smtp.return_value.__enter__.return_value.send_message.call_args_list]
        self.assertEqual((code, sent[0]["Subject"], sent[0]["To"]), (1, "Home search: run failed", "me@example.com"))


class Rendering(unittest.TestCase):
    def test_price_guide_shown_when_text_has_no_number(self):
        e = {"price_text": "SELLING UNDER THE MARKET VALUE!!", "price_low": 650000.0, "price_high": 650000.0}
        self.assertEqual(report._price(e), "SELLING UNDER THE MARKET VALUE!! (price guide $650,000)")

    def test_html_is_escaped(self):
        e, (section, reasons) = tag(item(1, "House", "<b>$700,000</b>", "350m²", "Brand new 22 squares double garage"))
        self.assertEqual(section, "main")
        e.update(section=section, reasons=reasons, duty="Duty: reduced duty", grant="", first_seen="2026-11-11")
        now = dt.datetime(2026, 11, 11, 7, tzinfo=MEL)
        rep = report.build({e["id"]: e}, [], [], [], now, "Wed 7am", True, 1, {})
        self.assertIn("&lt;b&gt;$700,000&lt;/b&gt;", rep["html"])


if __name__ == "__main__":
    unittest.main()
