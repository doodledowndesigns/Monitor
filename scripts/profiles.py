#!/usr/bin/env python3
"""Stakeholder profiles for every parliamentarian active on education since July 2024,
plus which parties own which issues.

For each member who asked DfE a written question or spoke in a saved education debate:
name, party, house, constituency, current government or opposition posts, current
committee memberships, questions to DfE per month, debates spoken in, and the topics
they raise most. Member details come from the Members API (cached in data/members_cache.json,
refreshed weekly). Writes data/dash/profiles-N.json (split to stay small) and
data/dash/parties.json (share of written questions by party for each topic, last 12 months).
"""
import datetime as dt
import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, START, get_json, load, save, today  # noqa: E402
from trends import COMPILED  # noqa: E402
from emerging import out_of_scope, BOILER  # noqa: E402

MEMBERS = "https://members-api.parliament.uk/api/Members"
CHUNK = 180_000


def months():
    out, y, m = [], 2024, 7
    t = today()
    while (y, m) <= (t.year, t.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def current(posts):
    now = today().isoformat()
    res = []
    for p in posts or []:
        end = (p.get("endDate") or "")[:10]
        if end and end < now:
            continue
        name = p.get("name") or p.get("additionalInfo")
        if name:
            res.append(name)
    return res


def since(posts):
    res = []
    for p in posts or []:
        end = (p.get("endDate") or "")[:10]
        if end and end < START:
            continue
        name = p.get("name")
        if name:
            res.append({"n": name, "from": (p.get("startDate") or "")[:10], "to": end or None})
    return res


def member_info(mid, cache):
    key = str(mid)
    c = cache.get(key)
    if c and c.get("fetched", "") >= (today() - dt.timedelta(days=7)).isoformat():
        return c
    m = (get_json(f"{MEMBERS}/{mid}") or {}).get("value") or {}
    bio = (get_json(f"{MEMBERS}/{mid}/Biography") or {}).get("value") or {}
    hm = m.get("latestHouseMembership") or {}
    info = {
        "n": m.get("nameDisplayAs"), "p": (m.get("latestParty") or {}).get("abbreviation"),
        "h": "Commons" if hm.get("house") == 1 else "Lords" if hm.get("house") == 2 else None,
        "seat": hm.get("membershipFrom"), "active": (hm.get("membershipStatus") or {}).get("statusIsActive"),
        "gov": current(bio.get("governmentPosts")), "opp": current(bio.get("oppositionPosts")),
        "other": current(bio.get("otherPosts"))[:3], "committees": current(bio.get("committeeMemberships"))[:6],
        "posts": (since(bio.get("governmentPosts")) + since(bio.get("oppositionPosts")))[:8],
        "fetched": today().isoformat(),
    } if m else (c or {})
    cache[key] = info
    return info


def main():
    ms = months()
    pos = {m: i for i, m in enumerate(ms)}
    people = defaultdict(lambda: {"wq": [0] * len(ms), "deb": 0, "tp": Counter(), "last": ""})
    names = {}
    party_topic = defaultdict(Counter)
    cutoff = (today() - dt.timedelta(days=365)).isoformat()
    for f in glob.glob(os.path.join(DATA, "questions", "*.json")):
        for r in load(f, []):
            mid = r.get("mid")
            if not mid or r.get("w"):
                continue
            head = r.get("hd") or ""
            q = BOILER.sub(" ", r.get("q") or "")
            if out_of_scope(head or q[:160]):
                continue
            tps = [t for t, rx in COMPILED if rx.search(f"{head}. {q}")]
            p = people[mid]
            if r["d"][:7] in pos:
                p["wq"][pos[r["d"][:7]]] += 1
            p["tp"].update(tps)
            p["last"] = max(p["last"], r["d"])
            names[mid] = (r.get("m"), r.get("p"), r.get("h"))
            if r["d"] >= cutoff:
                for t in tps:
                    party_topic[t][r.get("p") or "Other"] += 1
    for r in load(os.path.join(DATA, "index.json"), []):
        try:
            d = json.load(open(os.path.join(os.path.dirname(DATA), r["file"])))
        except Exception:
            continue
        for s in d.get("speakers", []):
            mid = s.get("member_id")
            if not mid or s.get("role") == "Chair":
                continue
            try:
                mid = int(mid)
            except Exception:
                continue
            p = people[mid]
            p["deb"] += 1
            p["last"] = max(p["last"], r["date"])
    cache = load(os.path.join(DATA, "members_cache.json"), {}) or {}
    out = []
    for mid, p in people.items():
        info = member_info(mid, cache)
        nm, pa, ho = names.get(mid, (None, None, None))
        out.append({"id": mid, "n": info.get("n") or nm, "p": info.get("p") or pa, "h": info.get("h") or ho, "seat": info.get("seat"),
                    "gov": info.get("gov") or [], "opp": info.get("opp") or [], "committees": info.get("committees") or [],
                    "posts": info.get("posts") or [], "wq": p["wq"], "deb": p["deb"],
                    "tp": dict(p["tp"].most_common(5)), "last": p["last"]})
    save(os.path.join(DATA, "members_cache.json"), cache)
    out.sort(key=lambda r: (-(sum(r["wq"]) + r["deb"]), r["n"] or ""))
    chunks, cur, size = [], [], 0
    for r in out:
        b = len(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
        if cur and size + b > CHUNK:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += b
    if cur:
        chunks.append(cur)
    for old in glob.glob(os.path.join(DATA, "dash", "profiles-*.json")):
        os.remove(old)
    for i, ch in enumerate(chunks, 1):
        save(os.path.join(DATA, "dash", f"profiles-{i}.json"), {"months": ms, "members": ch, "part": i, "parts": len(chunks)})
    parties = {t: dict(c.most_common()) for t, c in party_topic.items()}
    save(os.path.join(DATA, "dash", "parties.json"), {"since": cutoff, "to": today().isoformat(), "topics": parties,
                                                    "note": "Written questions to DfE by asking member's party, last 12 months."})
    print(f"profiles: {len(out)} members in {len(chunks)} parts")


if __name__ == "__main__":
    main()
