#!/usr/bin/env python3
"""Summarise saved Hansard debates into monthly topic trends for the dashboard.

Reads data/index.json and the debate files, assigns topics from titles (and parent
titles such as "Education" for oral questions), and writes data/trends.json:
  months: ["2024-07", ...]
  topics: {topic: [debates per month]}
  houses: {"Commons": [...], "Lords": [...]}
  speakers: [{name, party, house, debates, topics: {topic: n}}]  (top 60, excluding chairs)
  latest: the last date covered
Topic ids match the dashboard's meta/config topics.
"""
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

TOPICS = [
    ("send", r"SEND|special educational|EHCPs?|education, health and care|special needs|autis\w*|neurodiver\w*"),
    ("funding", r"funding|budgets?|spending|deficits?|pupil premium|finance"),
    ("workforce", r"teachers?|teaching|school staff|workforce|teachers'? pay|support staff"),
    ("curriculum", r"curricul\w*|exam\w*|GCSEs?|A[- ]levels?|assessment|SATs|oracy|RSHE|PSHE|music|arts education|history teaching|languages"),
    ("accountability", r"Ofsted|inspect\w*|accountability|league tables?|Ofqual|report cards?"),
    ("early_years", r"early years|childcare|child care|nurser\w*|best start|family hubs|early education"),
    ("fe", r"further education|colleges?|sixth form\w*|post-16|16 to 19|adult education|adult learning|ESOL"),
    ("skills", r"skills?|apprentice\w*|T[- ]levels?|V[- ]levels?|NEETs?|youth guarantee|careers|technical education|Skills England|growth and skills levy"),
    ("attendance", r"attendance|absence|exclusions?|behaviour|alternative provision"),
    ("disadvantage", r"free school meals|breakfast clubs?|poverty|disadvantag\w*|holiday activities|enrichment|school uniform"),
    ("wellbeing", r"mental health|wellbeing|safeguard\w*|bullying|online safety|smartphones?|mobile phones|antisemitism|misogyny"),
    ("structures", r"academ(y|ies)|trusts?|Children's Wellbeing and Schools|Education for All|white paper|local authorit\w* schools"),
    ("digital", r"\bAI\b|artificial intelligence|EdTech|digital|technology in schools"),
    ("estates", r"RAAC|school buildings|estate|concrete|rebuilding"),
    ("places", r"admissions|school places|falling rolls|closures?"),
    ("home_ed", r"home[- ]educat\w*|children not in school"),
    ("independent", r"private schools|independent schools|VAT"),
    ("process", r"Members: Correspondence|Parliamentary Questions|correspondence from"),
]
COMPILED = [(t, re.compile(r"\b(" + p + r")\b", re.I)) for t, p in TOPICS]


def topics_for(text):
    found = [t for t, rx in COMPILED if rx.search(text)]
    return found or ["general"]


def fill_parties(speakers, people):
    """Ministers often appear without a party; look them up once in the Members API (cached)."""
    import urllib.request
    cache_path = os.path.join(DATA, "members.json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    ids = {id(v): k for k, v in people.items()}
    for p in speakers:
        mid = ids.get(id(p))
        if p.get("party") or not isinstance(mid, int):
            continue
        if str(mid) not in cache:
            try:
                with urllib.request.urlopen(f"https://members-api.parliament.uk/api/Members/{mid}", timeout=30) as r:
                    v = json.load(r).get("value", {})
                cache[str(mid)] = (v.get("latestParty") or {}).get("abbreviation")
            except Exception:
                continue
        p["party"] = cache.get(str(mid))
    with open(cache_path, "w") as f:
        json.dump(cache, f)


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hansard import relevant
    index = [r for r in json.load(open(os.path.join(DATA, "index.json"))) if relevant(r["title"], r.get("parents") or [])]
    if not index:
        return
    months = sorted({r["date"][:7] for r in index})
    first, last = months[0], months[-1]
    # fill gaps so every month appears
    y, m = map(int, first.split("-"))
    allm = []
    while f"{y:04d}-{m:02d}" <= last:
        allm.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    pos = {mm: i for i, mm in enumerate(allm)}
    topics = defaultdict(lambda: [0] * len(allm))
    houses = defaultdict(lambda: [0] * len(allm))
    people = {}
    for r in index:
        text = " / ".join((r.get("parents") or []) + [r["title"]] + (r.get("subtitles") or []))
        tps = topics_for(text)
        i = pos[r["date"][:7]]
        for t in tps:
            topics[t][i] += 1
        houses[r["house"]][i] += 1
        try:
            d = json.load(open(os.path.join(ROOT, r["file"])))
        except Exception:
            continue
        for s in d.get("speakers", []):
            if s.get("role") == "Chair" or not s.get("name"):
                continue
            key = s.get("member_id") or s["name"]
            p = people.setdefault(key, {"name": s["name"], "house": r["house"], "debates": 0, "topics": Counter(), "_parties": Counter(), "_roles": Counter()})
            if s.get("party"):
                p["_parties"][s["party"]] += 1
            if s.get("role"):
                p["_roles"][s["role"]] += 1
            p["debates"] += 1
            for t in tps:
                p["topics"][t] += 1
    speakers_all = people
    speakers = sorted(people.values(), key=lambda p: -p["debates"])[:60]
    for p in speakers:
        p["topics"] = dict(p["topics"].most_common(4))
        p["party"] = p["_parties"].most_common(1)[0][0] if p["_parties"] else None
        p["role"] = p["_roles"].most_common(1)[0][0] if p["_roles"] else None
        del p["_parties"], p["_roles"]
    fill_parties(speakers, people)
    out = {
        "months": allm,
        "topics": dict(topics),
        "houses": dict(houses),
        "speakers": speakers,
        "debates": len(index),
        "latest": max(r["date"] for r in index),
        "note": "Education, schools, skills and FE debates in Hansard (Commons, Westminster Hall and Lords), by sitting month. Topics are assigned from debate titles.",
    }
    with open(os.path.join(DATA, "trends.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"trends: {len(index)} debates, {allm[0]} to {allm[-1]}")


if __name__ == "__main__":
    main()
