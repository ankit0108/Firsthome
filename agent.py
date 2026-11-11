"""First-home listing agent: fetch, tag, sort, compare, report, email.

    python agent.py               # normal run; when GitHub's scheduler starts it, sends once per 7am/6pm window
    python agent.py --dry-run     # build the report only: no email, state unchanged
    python agent.py --raw FILE    # use saved scraper output instead of calling Apify
"""
import argparse
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import report
import rules
import sources
import tagger

TZ = ZoneInfo(config.TIMEZONE)


def slot_for(now):
    minutes = now.hour * 60 + now.minute
    for name, (start, end) in config.SLOTS.items():
        if start <= minutes < end:
            return name
    return None


def load_state(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"listings": {}, "tags": {}, "last_sent": None}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch(raw_file=None):
    if raw_file:
        items = json.loads(Path(raw_file).read_text(encoding="utf-8"))
    else:
        items, info = sources.run_actor(sources.SCRAPER_A, sources.input_sweep(),
                                        max_charge_usd=config.RUN_CHARGE_CAP_USD, timeout_s=1800)
        print(f"Scraper: {len(items)} rows, usage US${info.get('usage_usd') or 0:.3f}")
    wanted = {s.lower() for s, _, _ in config.SUBURBS}
    rows, seen = [], set()
    for item in items:
        row = sources.normalise(item, "realestate.com.au")
        if not row["id"] or row["id"] in seen:
            continue
        if row["suburb"] and row["suburb"].lower() not in wanted:
            continue
        seen.add(row["id"])
        rows.append(row)
    return rows


def price_changed(old, new):
    if (old.get("price_low"), old.get("price_high")) != (new.get("price_low"), new.get("price_high")):
        return True
    return old.get("price_low") is None and old.get("price_text") != new.get("price_text")


def compare(prev, current, all_entries):
    new = [i for i in current if i not in prev]
    changed = [(prev[i], current[i]) for i in current if i in prev and price_changed(prev[i], current[i])]
    removed = []
    for i, old in prev.items():
        if i in current:
            continue
        e = all_entries.get(i)
        why = ("no longer fits: " + "; ".join(e["reasons"])) if e else "no longer listed (sold, under contract or withdrawn)"
        removed.append(dict(old, removed_reason=why))
    return new, changed, removed


def run(args):
    now = dt.datetime.now(TZ) if not args.now else dt.datetime.fromisoformat(args.now).astimezone(TZ)
    state_path = Path(args.state)
    state = load_state(state_path)
    slot = slot_for(now)
    today = now.date().isoformat()

    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        if not slot:
            print(f"{now:%H:%M} Melbourne is outside the 7am and 6pm windows: nothing to do.")
            return 0
        if state.get("last_sent") == {"date": today, "slot": slot}:
            print(f"The {config.SLOT_LABEL[slot]} report already went out today: nothing to do.")
            return 0

    rows = fetch(args.raw)
    if not rows:
        raise RuntimeError("The scraper returned no listings, so nothing was compared or sent.")
    tags, tag_cache, tag_stats = tagger.tag_all(rows, state.get("tags", {}))
    print(f"Tagging: {tag_stats}")

    prev = state.get("listings", {})
    entries = {}
    for row in rows:
        m = rules.merge(row, tags.get(row["id"]))
        section, reasons = rules.classify(m)
        duty, grant = rules.money_notes(m)
        first_seen = prev.get(row["id"], {}).get("first_seen", today)
        entries[row["id"]] = dict(m, section=section, reasons=reasons, duty=duty, grant=grant,
                                  first_seen=first_seen, last_seen=today)
    current = {i: e for i, e in entries.items() if e["section"] != "excluded"}
    first_run = not prev
    new, changed, removed = compare(prev, current, entries)

    label = f"{now:%a} {config.SLOT_LABEL[slot]}" if slot else f"{now:%a %H:%M}"
    rep = report.build(current, new, changed, removed, now, label, first_run, len(rows), tag_stats)

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "report.html").write_text(rep["html"], encoding="utf-8")
    (out / "report.txt").write_text(rep["subject"] + "\n\n" + rep["text"], encoding="utf-8")
    (out / "summary.md").write_text(rep["summary"], encoding="utf-8")
    (out / "entries.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    counts = {s: sum(e["section"] == s for e in entries.values()) for s in ("main", "near_miss", "flagged", "excluded")}
    print(f"Sections: {counts}")
    print(f"Subject: {rep['subject']}")

    dry = args.dry_run or os.environ.get("DRY_RUN", "").lower() == "true"
    settings = report.mail_settings()
    if dry:
        print("Dry run: report written to out/, no email sent, state unchanged.")
        return 0
    if not settings:
        print("Email secrets are missing, so nothing was sent and state is unchanged. Report is in out/.")
        return 0

    report.send(settings, rep["subject"], rep["html"], rep["text"])
    print(f"Sent to {len(settings['to'])} recipients.")
    save_state(state_path, {
        "listings": current,
        "tags": tag_cache,
        "last_sent": {"date": today, "slot": slot} if slot else state.get("last_sent"),
        "last_run": now.isoformat(timespec="minutes"),
    })
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--raw", help="saved scraper output (JSON list) to use instead of Apify")
    p.add_argument("--state", default="state/state.json")
    p.add_argument("--out", default="out")
    p.add_argument("--now", help="pretend it's this time (ISO format), for tests")
    args = p.parse_args(argv)
    try:
        return run(args)
    except Exception:  # noqa: BLE001 - report every failure by email
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        settings = report.mail_settings()
        dry = args.dry_run or os.environ.get("DRY_RUN", "").lower() == "true"
        if settings and not dry:
            try:
                report.send_error(settings, details)
            except Exception as e:  # noqa: BLE001
                print(f"Couldn't send the error email either: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
