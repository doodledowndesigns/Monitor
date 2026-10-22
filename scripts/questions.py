#!/usr/bin/env python3
"""Fetch every written question to the Department for Education since the 2024 election.

Saves one file per month under data/questions/YYYY-MM.json. Each record:
  uin, d (tabled), h (house), hd (heading), q (question, boilerplate trimmed),
  m (asking member), mid (member id), p (party), a (answered date or null), w (withdrawn)
First run backfills from July 2024; later runs refetch the last three months so
answers and headings added after tabling are picked up.

Usage: python scripts/questions.py [full]
Standard library only.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "questions")
START = dt.date(2024, 7, 4)
DFE = 60
TAKE = 100

BOILER = re.compile(
    r"^To ask (the )?(Secretary of State for Education|His Majesty's Government)[,:]?\s*|"
    r"^To ask the Secretary of State for Education[^,]*,\s*",
    re.I,
)


def get(params, retries=4):
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "education-monitor/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            time.sleep(0.3)
            return data
        except Exception as e:
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return None


def month_bounds(y, m):
    first = dt.date(y, m, 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return max(first, START), nxt - dt.timedelta(days=1)


def compact(v):
    am = v.get("askingMember") or {}
    q = re.sub(r"\s+", " ", BOILER.sub("", v.get("questionText") or "")).strip()
    return {
        "uin": v.get("uin"),
        "d": (v.get("dateTabled") or "")[:10],
        "h": v.get("house"),
        "hd": v.get("heading"),
        "q": q[:400],
        "m": am.get("name"),
        "mid": v.get("askingMemberId"),
        "p": am.get("partyAbbreviation"),
        "a": (v.get("dateAnswered") or "")[:10] or None,
        "w": bool(v.get("isWithdrawn")),
    }


def fetch_month(y, m):
    lo, hi = month_bounds(y, m)
    if lo > hi:
        return None
    out, skip, total = [], 0, None
    while True:
        data = get({"answeringBodies": DFE, "tabledWhenFrom": lo.isoformat(), "tabledWhenTo": hi.isoformat(),
                    "take": TAKE, "skip": skip, "expandMember": "true"})
        if data is None:
            print(f"  ! {y}-{m:02d} failed at skip {skip}", file=sys.stderr)
            return None
        total = data.get("totalResults", 0)
        for r in data.get("results", []):
            out.append(compact(r.get("value", r)))
        skip += TAKE
        if skip >= total or not data.get("results"):
            break
    seen, uniq = set(), []
    for r in out:
        if r["uin"] in seen:
            continue
        seen.add(r["uin"])
        uniq.append(r)
    uniq.sort(key=lambda r: (r["d"], str(r["uin"])))
    return uniq


def main():
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today()
    months = []
    y, m = START.year, START.month
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    full = len(sys.argv) > 1 and sys.argv[1] == "full"
    recent = set(months[-3:])
    n = 0
    for y, m in months:
        path = os.path.join(OUT, f"{y}-{m:02d}.json")
        if os.path.exists(path) and not full and (y, m) not in recent:
            continue
        recs = fetch_month(y, m)
        if recs is None:
            continue
        with open(path, "w") as f:
            json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))
        n += len(recs)
        print(f"{y}-{m:02d}: {len(recs)} questions")
    print(f"questions: wrote {n} records")


if __name__ == "__main__":
    main()
