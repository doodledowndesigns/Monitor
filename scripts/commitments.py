#!/usr/bin/env python3
"""Find candidate ministerial commitments in saved education debates.

Looks at every contribution by a minister (or government whip answering for one) and
keeps sentences that promise future action with a time attached, such as "we will
publish the strategy in the spring" or "I will write to the hon. Member shortly". These
are candidates only: the dashboard refresh reviews them and records the genuine ones.
Writes data/dash/commitment_candidates.json (newest first, last 18 months).
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, load, save, today  # noqa: E402

MINISTER = re.compile(r"Minister|Secretary of State|Under-Secretary|Lord in Waiting|Baroness in Waiting|Government Whip", re.I)
PROMISE = re.compile(r"\b(we will|we'll|I will|I'll|the Government will|the Department will|we are going to|we intend to|we plan to|"
                     r"we expect to|we aim to|we are committed to|will be published|will publish|will set out|will bring forward|"
                     r"will consult|will introduce|will legislate|will respond|will launch|will be launched|will be introduced|will come forward)\b", re.I)
WHEN = re.compile(r"\b(spring|summer|autumn|winter|new year|in due course|shortly|soon|coming (weeks|months)|"
                  r"(this|next) (year|month|term|session|academic year)|later this year|early next year|by the end of|"
                  r"(January|February|March|April|May|June|July|August|September|October|November|December)( 20\d\d)?|"
                  r"20\d\d(-| to |/)\d\d|20\d\d)\b", re.I)
ROUTINE = re.compile(r"\b(write to (the|my) (hon|noble)|happy to meet|meet (him|her|the hon)|look into|take (that|this) away|"
                     r"I will come on to|I will turn to|I will now|I will give way|I will be brief|I will finish|I will conclude)\b", re.I)


def sentences(text):
    return re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", text or "")


def main():
    cutoff = (today() - dt.timedelta(days=548)).isoformat()
    out = []
    for r in load(os.path.join(DATA, "index.json"), []):
        if r["date"] < cutoff:
            continue
        try:
            d = json.load(open(os.path.join(os.path.dirname(DATA), r["file"])))
        except Exception:
            continue
        for c in d.get("contributions", []):
            role = c.get("role") or ""
            if not MINISTER.search(role):
                continue
            for s in sentences(c.get("text")):
                if len(s) < 40 or not PROMISE.search(s) or not WHEN.search(s) or ROUTINE.search(s):
                    continue
                out.append({"d": r["date"], "who": c.get("name"), "role": role, "house": r["house"], "t": d.get("title"),
                            "u": d.get("url"), "s": s.strip()[:500]})
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: c["d"], reverse=True):
        k = c["s"][:120]
        if k in seen:
            continue
        seen.add(k)
        c["id"] = "c-" + c["d"].replace("-", "") + "-" + hashlib.sha1(k.encode()).hexdigest()[:6]
        uniq.append(c)
    save(os.path.join(DATA, "dash", "commitment_candidates.json"), uniq)
    print(f"commitments: {len(uniq)} candidate sentences")


if __name__ == "__main__":
    main()
