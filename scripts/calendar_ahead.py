#!/usr/bin/env python3
"""Forward look: education business in Parliament over the next five weeks.

Reads the Parliament What's On calendar and keeps events about schools, SEND, early
years, FE, skills or the Department for Education: DfE oral questions, Westminster Hall
and chamber debates, Lords questions, bill stages, statements and Education Committee
sessions. Writes data/dash/calendar.json.
"""
import datetime as dt
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, get_json, first, save, today  # noqa: E402
from hansard import INCLUDE, EXCLUDE, CORE  # noqa: E402

API = "https://whatson-api.parliament.uk/calendar/events/list.json"
DFE = 60
ED_COMMITTEE = 203


def txt(e):
    parts = [first(e, "Description") or "", first(e, "Notes") or "", first(e, "Category") or "", first(e, "Type") or "",
             first(e, "BillName") or "", (first(e, "Committee") or {}).get("Description", "") if isinstance(first(e, "Committee"), dict) else ""]
    for a in e.get("EventActivities") or []:
        parts.append(first(a, "Description") or "")
    return " ".join(str(p) for p in parts)


def relevant(e, bills):
    com = e.get("Committee") or {}
    if isinstance(com, dict) and com.get("Id") == ED_COMMITTEE:
        return True
    t = txt(e)
    if any(b and b.lower() in t.lower() for b in bills):
        return True
    if re.search(r"\bEducation\b", first(e, "Description") or "") and re.search(r"question", t, re.I):
        return True
    return bool(INCLUDE.search(t)) and not (EXCLUDE.search(t) and not CORE.search(t))


def main():
    start = today()
    end = start + dt.timedelta(days=35)
    bills = [b.get("shortTitle", "").replace(" [HL]", "") for b in (get_json("https://bills-api.parliament.uk/api/v1/Bills", {"SearchTerm": "school", "Take": 50}) or {}).get("items", [])]
    events = []
    day = start
    while day <= end:  # one day per call: the API returns at most 100 events per request
        for house in ("Commons", "Lords", "JointCommittee"):
            data = get_json(API, {"queryParameters.startDate": day.isoformat(), "queryParameters.endDate": day.isoformat(), "queryParameters.house": house})
            if isinstance(data, list):
                events += data
        day += dt.timedelta(days=1)
    out, seen = [], set()
    for e in events:
        if not relevant(e, bills):
            continue
        eid = e.get("Id")
        if eid in seen:
            continue
        seen.add(eid)
        com = e.get("Committee") or {}
        members = [first(m, "Name", "NameDisplayAs") for m in (e.get("Members") or []) if isinstance(m, dict)]
        out.append({
            "id": eid,
            "d": (first(e, "StartDate") or "")[:10],
            "time": (first(e, "StartTime") or "")[:5] or None,
            "house": first(e, "House"),
            "type": first(e, "Type"),
            "cat": first(e, "Category"),
            "t": re.sub(r"\s+", " ", first(e, "Description") or "").strip(),
            "notes": re.sub(r"<[^>]+>|\s+", " ", first(e, "Notes") or "").strip()[:300] or None,
            "where": first(e, "Location"),
            "committee": com.get("Description") if isinstance(com, dict) else None,
            "bill": first(e, "BillName"),
            "billId": first(e, "BillId"),
            "members": [m for m in members if m][:8],
            "cancelled": bool(first(e, "CancelledDate")),
        })
    out.sort(key=lambda r: (r["d"], r["time"] or "99", r["t"]))
    save(os.path.join(DATA, "dash", "calendar.json"), {"from": start.isoformat(), "to": end.isoformat(), "events": out,
                                                     "source": "UK Parliament What's On"})
    print(f"calendar: {len(out)} education events of {len(events)}")


if __name__ == "__main__":
    main()
