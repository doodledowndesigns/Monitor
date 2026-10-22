#!/usr/bin/env python3
"""Consultations: every government consultation and select committee inquiry on education and skills.

Government: consultations since July 2024 from the education departments and agencies on GOV.UK
(DfE, Ofsted, Ofqual, Skills England and others), plus any other department's consultation whose
title is about schools, early years, FE or skills. Opening and closing dates come from the GOV.UK
content API (cached, so only open or new consultations are re-read each run).

Committees: current inquiries of every Commons, Lords and joint select committee whose work is on
education (the Education Committee's are all included), with the evidence deadline from the
committee's call for evidence.

Higher education and children's social care are left out, as elsewhere in the monitor.
Writes data/dash/consultations.json.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hansard import INCLUDE, EXCLUDE, CORE  # noqa: E402
from trends import COMPILED  # noqa: E402
from util import DATA, START, get_json, load, save, today  # noqa: E402

SEARCH = "https://www.gov.uk/api/search.json"
CONTENT = "https://www.gov.uk/api/content"
COMMITTEES = "https://committees-api.parliament.uk/api"
ED_ORGS = {
    "department-for-education": "DfE", "ofsted": "Ofsted", "ofqual": "Ofqual", "skills-england": "Skills England",
    "standards-and-testing-agency": "STA", "teaching-regulation-agency": "TRA",
    "education-and-skills-funding-agency": "ESFA", "institute-for-apprenticeships-and-technical-education": "IfATE",
    "office-of-the-schools-adjudicator": "Schools Adjudicator",
}
KINDS = ["open_consultation", "closed_consultation", "consultation_outcome"]
TERMS = ["school", "schools", "education", "skills", "apprenticeship", "childcare", "early years", "further education",
         "special educational needs", "teachers", "pupils", "colleges", "curriculum"]
CARE = re.compile(r"looked after|children in need|social care|care leavers|children's homes|care standards|foster|adoption", re.I)
ED_COMMITTEE = 203


def in_scope(text, title):
    if (EXCLUDE.search(text) or CARE.search(title)) and not CORE.search(title):
        return False
    return True


def topics(text):
    return [t for t, rx in COMPILED if rx.search(text) and t != "process"][:2]


def search(params):
    out, start = [], 0
    while start < 2000:
        data = get_json(SEARCH, params | {"count": 200, "start": start}) or {}
        res = data.get("results", [])
        out += res
        start += len(res)
        if not res or start >= data.get("total", 0):
            break
    return out


def government():
    now = today().isoformat()
    cache = load(os.path.join(DATA, "consultations_cache.json"), {}) or {}
    fields = ["title", "link", "public_timestamp", "description", "organisations", "content_store_document_type"]
    found = {}
    for kind in KINDS:
        for r in search({"filter_organisations": list(ED_ORGS), "filter_content_store_document_type": kind,
                         "filter_public_timestamp": f"from:{START}", "fields": fields}):
            found[r["link"]] = r | {"_ed": True}
        for q in TERMS:
            for r in search({"q": q, "filter_content_store_document_type": kind, "filter_public_timestamp": f"from:{START}",
                             "fields": fields}):
                if r["link"] not in found and INCLUDE.search(r.get("title") or ""):
                    found[r["link"]] = r | {"_ed": False}
    rows = []
    for link, r in found.items():
        title = r.get("title") or ""
        desc = r.get("description") or ""
        if not in_scope(title + " " + desc, title):
            continue
        kind = r.get("content_store_document_type")
        c = cache.get(link)
        if not c or c.get("kind") != kind or kind == "open_consultation":
            content = get_json(CONTENT + link) or {}
            det = content.get("details") or {}
            c = {"kind": kind, "opens": (det.get("opening_date") or "")[:10] or None,
                 "closes": (det.get("closing_date") or "")[:10] or None}
            cache[link] = c
        orgs = []
        for o in r.get("organisations") or []:
            if isinstance(o, dict):
                orgs.append(ED_ORGS.get(o.get("slug")) or o.get("acronym") or o.get("title"))
        opens = c["opens"] or (r.get("public_timestamp") or "")[:10] or None
        closes = c["closes"]
        if kind == "consultation_outcome":
            status = "outcome"
        elif kind == "open_consultation" and (closes or "9999") >= now:
            status = "open"
        else:
            status = "closed"
        rows.append({"src": "gov", "t": title, "u": "https://www.gov.uk" + link, "by": ", ".join(o for o in orgs if o) or "Government",
                     "opens": opens, "closes": closes, "status": status, "tp": topics(title + " " + desc), "x": desc[:200] or None})
    save(os.path.join(DATA, "consultations_cache.json"), cache)
    return rows


def committees():
    now = today().isoformat()
    coms, skip = [], 0
    while skip < 1500:
        data = get_json(f"{COMMITTEES}/Committees", {"CommitteeStatus": "Current", "Take": 256, "Skip": skip}) or {}
        items = data.get("items", [])
        coms += items
        skip += len(items)
        if not items or skip >= data.get("totalResults", 0):
            break
    rows = []
    for com in coms:
        cid = com.get("id")
        name = com.get("name") or ""
        house = com.get("house") or ""
        skip = 0
        while skip < 500:
            data = get_json(f"{COMMITTEES}/CommitteeBusiness", {"CommitteeId": cid, "Status": "Open", "Take": 100, "Skip": skip}) or {}
            items = data.get("items", [])
            skip += len(items)
            for b in items:
                typ = (b.get("type") or {})
                periods = (b.get("openSubmissionPeriods") or []) + (b.get("closedSubmissionPeriods") or [])
                if not (typ.get("isInquiry") or periods):
                    continue
                title = b.get("title") or ""
                if cid != ED_COMMITTEE and not INCLUDE.search(title):
                    continue
                if not in_scope(title, title):
                    continue
                ends = sorted((p.get("endDate") or "")[:10] for p in periods if p.get("endDate"))
                open_p = [(p.get("endDate") or "")[:10] for p in b.get("openSubmissionPeriods") or [] if p.get("endDate")]
                deadline = min(open_p) if open_p else (ends[-1] if ends else None)
                evidence = "open" if open_p and min(open_p) >= now else ("closed" if ends else "none")
                rows.append({"src": "committee", "t": title, "u": f"https://committees.parliament.uk/work/{b.get('id')}/",
                             "by": name, "house": house, "opens": (b.get("openDate") or "")[:10] or None, "closes": deadline,
                             "status": "open" if evidence == "open" else "closed" if evidence == "closed" else "ongoing",
                             "kind": typ.get("name"), "tp": topics(title)})
            if not items or skip >= data.get("totalResults", 0):
                break
    return rows


def main():
    gov = government()
    com = committees()
    rows = gov + com
    rows.sort(key=lambda r: r["closes"] or "9999")
    save(os.path.join(DATA, "dash", "consultations.json"), {"generated": today().isoformat(), "since": START, "items": rows})
    print(f"consultations: {len(gov)} government ({sum(r['status'] == 'open' for r in gov)} open), "
          f"{len(com)} committee inquiries ({sum(r['status'] == 'open' for r in com)} taking evidence)")


if __name__ == "__main__":
    main()
