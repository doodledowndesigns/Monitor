#!/usr/bin/env python3
"""Deadlines: open consultations, upcoming statistics releases, and committee reports
awaiting a government response.

- Consultations (DfE, Ofsted, Ofqual) from the GOV.UK search API, with closing dates
  from the GOV.UK content API. Keeps open ones and any closed in the last 60 days.
- Statistics release announcements (DfE, Ofsted, Ofqual) for the next 90 days.
- Education Committee reports since July 2024 and whether the government has responded.
  The government normally replies within two months of a report.
Writes data/dash/deadlines.json.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hansard import EXCLUDE, CORE  # noqa: E402
from util import DATA, START, get_json, first, save, today  # noqa: E402

SEARCH = "https://www.gov.uk/api/search.json"
ORGS = ["department-for-education", "ofsted", "ofqual"]
ORGNAME = {"department-for-education": "DfE", "ofsted": "Ofsted", "ofqual": "Ofqual"}
COMMITTEE = 203


def search(params):
    out, start = [], 0
    while True:
        data = get_json(SEARCH, params | {"count": 500, "start": start}) or {}
        res = data.get("results", [])
        out += res
        start += len(res)
        if not res or start >= data.get("total", 0):
            return out


def consultations():
    now = today()
    rows = []
    for kind in ("open_consultation", "closed_consultation"):
        for r in search({"filter_organisations": ORGS, "filter_content_store_document_type": kind,
                         "filter_public_timestamp": f"from:{(now - dt.timedelta(days=200)).isoformat()}",
                         "fields": ["title", "link", "public_timestamp", "description", "organisations"]}):
            link = r.get("link") or ""
            content = get_json("https://www.gov.uk/api/content" + link) or {}
            det = content.get("details") or {}
            closes = (det.get("closing_date") or "")[:10] or None
            opens = (det.get("opening_date") or r.get("public_timestamp") or "")[:10] or None
            if closes and closes < (now - dt.timedelta(days=60)).isoformat():
                continue
            orgs = [ORGNAME.get(o.get("slug"), o.get("acronym") or o.get("title")) for o in (r.get("organisations") or []) if isinstance(o, dict)]
            rows.append({"t": r.get("title"), "u": "https://www.gov.uk" + link, "opens": opens, "closes": closes,
                         "status": "open" if (closes or "9999") >= now.isoformat() else "closed",
                         "org": ", ".join([o for o in orgs if o]) or "DfE", "x": (r.get("description") or "")[:240]})
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["closes"] or "9999"):
        if r["u"] in seen:
            continue
        seen.add(r["u"])
        out.append(r)
    return out


def stats():
    now = today()
    rows = []
    for kind in ("official_statistics_announcement", "national_statistics_announcement"):
        for r in search({"filter_organisations": ORGS, "filter_content_store_document_type": kind,
                         "filter_release_timestamp": f"from:{now.isoformat()}",
                         "fields": ["title", "link", "release_timestamp", "organisations", "statistics_announcement_state"]}):
            rel = (r.get("release_timestamp") or "")[:10]
            if not rel or rel > (now + dt.timedelta(days=90)).isoformat():
                continue
            orgs = [ORGNAME.get(o.get("slug"), o.get("acronym") or o.get("title")) for o in (r.get("organisations") or []) if isinstance(o, dict)]
            rows.append({"t": r.get("title"), "u": "https://www.gov.uk" + (r.get("link") or ""), "d": rel,
                         "state": r.get("statistics_announcement_state"), "org": ", ".join([o for o in orgs if o]) or "DfE"})
    rows.sort(key=lambda r: r["d"])
    return rows


def words(s):
    return set(w for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in {"report", "government", "response", "committee", "education", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "special", "session"})


def committee():
    pubs, skip = [], 0
    while skip < 1000:
        data = get_json("https://committees-api.parliament.uk/api/Publications", {"CommitteeId": COMMITTEE, "StartDate": START, "Take": 100, "Skip": skip}) or {}
        items = data.get("items", [])
        pubs += items
        if len(items) < 100:
            break
        skip += 100
    reports, responses = [], []
    for p in pubs:
        typ = ((p.get("type") or {}).get("name") or "")
        desc = p.get("description") or ""
        d = (p.get("publicationStartDate") or "")[:10]
        url = first(p, "additionalContentUrl") or f"https://committees.parliament.uk/publications/{p.get('id')}/"
        rec = {"t": desc, "d": d, "u": url, "type": typ}
        if re.search(r"government response|special report", typ + " " + desc, re.I) and re.search(r"response", typ + " " + desc, re.I):
            responses.append(rec)
        elif re.search(r"^report", typ, re.I) or (typ == "" and re.search(r"report", desc, re.I)):
            reports.append(rec)
    now = today()
    out = []
    for r in sorted(reports, key=lambda r: r["d"], reverse=True):
        w = words(r["t"])
        match = None
        for g in responses:
            if g["d"] >= r["d"] and len(w & words(g["t"])) >= max(2, len(w) // 2):
                match = g
                break
        due = (dt.date.fromisoformat(r["d"]) + dt.timedelta(days=61)).isoformat() if r["d"] else None
        out.append({"t": r["t"], "d": r["d"], "u": r["u"], "due": due, "responded": match["d"] if match else None,
                    "responseUrl": match["u"] if match else None,
                    "status": "responded" if match else ("overdue" if due and due < now.isoformat() else "awaiting")})
    return out


def main():
    care = re.compile(r"looked after|children in need|social care|care leavers|children's homes|care standards", re.I)
    # Accessible versions duplicate a report, and pre-appointment reports get no formal response
    variant = re.compile(r"^(Large Print|Easy Read|BSL|Audio)\b|Appointment of ", re.I)

    def keep(rows):
        return [r for r in rows if not ((EXCLUDE.search(r.get("t", "") + " " + (r.get("x") or "")) or care.search(r.get("t", "")))
                                        and not CORE.search(r.get("t", ""))) and not variant.search(r.get("t", ""))]
    res = {"generated": today().isoformat(), "consultations": keep(consultations()), "stats": keep(stats()), "reports": keep(committee())}
    save(os.path.join(DATA, "dash", "deadlines.json"), res)
    print(f"deadlines: {len(res['consultations'])} consultations, {len(res['stats'])} stats releases, {len(res['reports'])} reports")


if __name__ == "__main__":
    main()
