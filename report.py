"""Build the email report (HTML and plain text) and send it through Gmail."""
import datetime as dt
import html
import os
import smtplib
import ssl
from email.message import EmailMessage

import config
from rules import TYPE_LABEL

GROUPS = [("house_and_land_package", "House and land packages"), ("new_house", "New houses"), ("land", "Titled land")]


def _money(v):
    return f"${v:,.0f}" if v is not None else "not shown"


def _sort_key(e):
    return (e.get("price_low") is None, e.get("price_low") or 0)


def _price(e):
    text = e.get("price_text") or ""
    if e.get("price_low") and not any(ch.isdigit() for ch in text):
        guide = _money(e["price_low"]) if e.get("price_high") in (None, e["price_low"]) else f"{_money(e['price_low'])}-{_money(e['price_high'])}"
        return f"{text} (price guide {guide})" if text else f"Price guide {guide}"
    return text or "Price not shown"


def _facts(e):
    parts = []
    if e.get("lot_m2"):
        parts.append(f"Lot {e['lot_m2']:,.0f} m²")
    if e.get("frontage_m"):
        parts.append(f"Frontage {e['frontage_m']:g} m")
    if e.get("house_sq"):
        parts.append(f"{e['house_sq']:g} squares")
    rooms = []
    if e.get("bedrooms"):
        rooms.append(f"{e['bedrooms']:g} bed" if isinstance(e["bedrooms"], (int, float)) else f"{e['bedrooms']} bed")
    if e.get("bathrooms"):
        rooms.append(f"{e['bathrooms']:g} bath" if isinstance(e["bathrooms"], (int, float)) else f"{e['bathrooms']} bath")
    if e.get("garage"):
        rooms.append(f"{e['garage']:g} garage")
    if rooms:
        parts.append(" ".join(rooms))
    return " · ".join(parts)


def _notes(e, today):
    parts = [TYPE_LABEL.get(e["type"], e["type"])]
    if e["type"] == "land" and e.get("titled") == "titled":
        parts[0] = "Titled land"
    parts += [p for p in (e.get("duty"), e.get("grant")) if p]
    if e.get("first_seen"):
        days = (today - dt.date.fromisoformat(e["first_seen"])).days
        parts.append("new today" if days == 0 else f"seen {days} day{'s' if days != 1 else ''}")
    return " · ".join(parts)


def _card_html(e, today, extra=""):
    esc = html.escape
    title = esc(e.get("address") or "Address not shown")
    link = f'<a href="{esc(e["url"])}" style="color:#1a56db;text-decoration:none">{title}</a>' if e.get("url") else title
    lines = [
        f'<div style="padding:10px 0;border-bottom:1px solid #e5e7eb">',
        f'<div style="font-weight:600">{link} <span style="color:#6b7280;font-weight:400">· {esc(e.get("suburb", ""))}</span></div>',
        f'<div style="font-weight:600">{esc(_price(e))}</div>',
    ]
    facts = _facts(e)
    if facts:
        lines.append(f'<div>{esc(facts)}</div>')
    lines.append(f'<div style="color:#4b5563">{esc(_notes(e, today))}</div>')
    if extra:
        lines.append(f'<div style="color:#b45309">{esc(extra)}</div>')
    if e.get("reasons") and e.get("section") != "main":
        lines.append(f'<div style="color:#b91c1c">{esc("; ".join(e["reasons"]))}</div>')
    lines.append("</div>")
    return "\n".join(lines)


def _card_text(e, today, extra=""):
    out = [f"- {e.get('address') or 'Address not shown'}, {e.get('suburb', '')}", f"  {_price(e)}"]
    facts = _facts(e)
    if facts:
        out.append(f"  {facts}")
    out.append(f"  {_notes(e, today)}")
    if extra:
        out.append(f"  {extra}")
    if e.get("reasons") and e.get("section") != "main":
        out.append(f"  Check: {'; '.join(e['reasons'])}")
    if e.get("url"):
        out.append(f"  {e['url']}")
    return "\n".join(out)


def build(current, new_ids, changed, removed, now, label, first_run, scanned, tag_stats):
    """Return dict with subject, html, text and a short markdown summary."""
    today = now.date()
    cap = config.MAX_PER_SECTION
    main = sorted((e for e in current.values() if e["section"] == "main"), key=_sort_key)
    near = sorted((e for e in current.values() if e["section"] == "near_miss"), key=_sort_key)
    flagged = sorted((e for e in current.values() if e["section"] == "flagged"), key=_sort_key)
    new = sorted((current[i] for i in new_ids), key=_sort_key)

    if first_run:
        subject = f"Home search: {len(main)} matches, first report ({label})"
    else:
        subject = f"Home search: {len(new)} new, {len(changed)} price change{'s' if len(changed) != 1 else ''} ({label})"

    h, t = [], []
    h.append('<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;line-height:1.45;color:#111827;max-width:680px">')
    intro = (f"{len(main)} listings match every rule. {len(near)} near misses and {len(flagged)} to check are further down. "
             f"{scanned} listings scanned across {len(config.SUBURBS)} suburbs.")
    h.append(f"<p>{html.escape(intro)}</p>")
    t.append(intro)

    def section(title, items, card_extra=None, note=""):
        if not items:
            return
        shown = items[:cap]
        h.append(f'<h2 style="font-size:17px;margin:22px 0 4px">{html.escape(title)} ({len(items)})</h2>')
        t.append(f"\n{title.upper()} ({len(items)})")
        if note:
            h.append(f'<p style="color:#6b7280;margin:0 0 4px">{html.escape(note)}</p>')
            t.append(note)
        for e in shown:
            extra = card_extra(e) if card_extra else ""
            h.append(_card_html(e, today, extra))
            t.append(_card_text(e, today, extra))
        if len(items) > cap:
            more = f"And {len(items) - cap} more not shown."
            h.append(f"<p>{more}</p>")
            t.append(more)

    if first_run:
        h.append('<p style="color:#6b7280">First report: everything below is new. From the next report, new listings and price changes are listed first.</p>')
        t.append("First report: from the next one, new listings and price changes are listed first.")
    else:
        section("New since last report", new)
        if changed:
            by_id = {c[1]["id"]: c[0] for c in changed}
            section("Price changes", sorted((c[1] for c in changed), key=_sort_key),
                    card_extra=lambda e: f"Was: {by_id[e['id']].get('price_text') or 'not shown'}")

    for kind, title in GROUPS:
        section(f"Matches: {title.lower()}", [e for e in main if e["type"] == kind])
    section("Near misses", near, note="Close on one rule; the reason is under each.")
    section("To check: details missing from the ad", flagged,
            note="These may fit, but the ad doesn't state something the rules need.")

    if removed and not first_run:
        h.append(f'<h2 style="font-size:17px;margin:22px 0 4px">Removed since last report ({len(removed)})</h2><ul>')
        t.append(f"\nREMOVED SINCE LAST REPORT ({len(removed)})")
        for e in removed[:cap]:
            line = f"{e.get('address') or 'Address not shown'}, {e.get('price_text') or ''}: {e['removed_reason']}"
            h.append(f"<li>{html.escape(line)}</li>")
            t.append(f"- {line}")
        h.append("</ul>")

    foot = (f"Duty and grant notes are estimates: confirm with a conveyancer or the SRO calculator. "
            f"Rules: lot {config.LOT_MIN}-{config.LOT_MAX} m², house {config.HOUSE_MIN_SQUARES:g}+ squares, "
            f"double garage, up to ${config.CAP_HOUSE_OR_PACKAGE:,} (land ${config.CAP_TITLED_LAND:,}). "
            f"Tagging: {tag_stats.get('ai', 0) + tag_stats.get('cached', 0)} cached or AI, "
            f"{tag_stats.get('rules', 0) + tag_stats.get('ai_failed', 0)} by rules. Run {now:%a %d %b %Y %H:%M}.")
    h.append(f'<p style="color:#6b7280;font-size:12px;margin-top:24px">{html.escape(foot)}</p></div>')
    t.append("\n" + foot)

    md = [f"## {subject}", "", intro, "",
          f"| Section | Count |", "| --- | --- |",
          f"| Matches | {len(main)} |", f"| Near misses | {len(near)} |", f"| To check | {len(flagged)} |",
          f"| New since last report | {0 if first_run else len(new)} |", f"| Price changes | {len(changed)} |",
          f"| Removed | {0 if first_run else len(removed)} |", ""]
    if main:
        md += ["### Matches", ""] + [f"- [{e.get('address') or 'Address not shown'}]({e.get('url')}) · {_price(e)} · {_facts(e)}" for e in main[:30]]
    return {"subject": subject, "html": "\n".join(h), "text": "\n".join(t), "summary": "\n".join(md) + "\n"}


# ---------- email ----------

def mail_settings():
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = [a.strip() for a in os.environ.get("REPORT_RECIPIENTS", "").split(",") if a.strip()]
    if sender and password and to:
        return {"sender": sender, "password": password, "to": to}
    return None


def send(settings, subject, html_body, text_body, to=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["sender"]
    msg["To"] = ", ".join(to or settings["to"])
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(settings["sender"], settings["password"])
        smtp.send_message(msg)


def send_error(settings, details):
    body = "The home search run failed, so no report went out.\n\n" + details[-3000:]
    send(settings, "Home search: run failed", f"<pre>{html.escape(body)}</pre>", body, to=[settings["sender"]])
