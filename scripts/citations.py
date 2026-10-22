#!/usr/bin/env python3
"""Where research organisations are cited in Parliament since July 2024.

Searches all of Hansard (spoken and written contributions, every subject, both Houses)
and all written questions and answers for a list of education research and sector bodies, keeping the
sentence that names them. Writes data/dash/citations.json.
"""
import datetime as dt
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, START, get_json, first, save, today  # noqa: E402

HANSARD = "https://hansard-api.parliament.uk"
WQ = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
# Education research and sector bodies, treated identically and listed alphabetically.
# (The Institute for Fiscal Studies is left out: most of its mentions are about tax, not education.)
ORGS = [
    ("Ambition Institute", ["Ambition Institute"]),
    ("Chartered College of Teaching", ["Chartered College of Teaching"]),
    ("Edge Foundation", ["Edge Foundation"]),
    ("EEF", ["Education Endowment Foundation"]),
    ("EPI", ["Education Policy Institute"]),
    ("FFT Education Datalab", ["FFT Education Datalab", "Education Datalab"]),
    ("Learning and Work Institute", ["Learning and Work Institute"]),
    ("NFER", ["NFER", "National Foundation for Educational Research"]),
    ("Nuffield Foundation", ["Nuffield Foundation"]),
    ("Sutton Trust", ["Sutton Trust"]),
    ("Teach First", ["Teach First"]),
]
KEEP = 30  # most recent citations kept per organisation; counts and months cover them all



def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def snippet(text, names):
    text = clean(text)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", text)
    for i, s in enumerate(sents):
        if any(re.search(r"\b" + re.escape(n) + r"\b", s, re.I if " " in n else 0) for n in names):
            out = s if len(s) > 80 or i + 1 >= len(sents) else s + " " + sents[i + 1]
            return out[:320]
    return None


def hansard(org, names):
    out = []
    for name in names:
        for ctype in ("Spoken", "Written"):
            skip = 0
            while skip < 600:
                data = get_json(f"{HANSARD}/search/contributions/{ctype}.json", {
                    "queryParameters.searchTerm": f'"{name}"', "queryParameters.startDate": START,
                    "queryParameters.endDate": today().isoformat(), "queryParameters.take": 50, "queryParameters.skip": skip})
                res = (data or {}).get("Results") or (data or {}).get("Contributions") or []
                for r in res:
                    txt = first(r, "ContributionTextFull", "ContributionText") or ""
                    snip = snippet(txt, names)
                    if not snip:
                        continue
                    house = first(r, "House")
                    date = (first(r, "SittingDate") or "")[:10]
                    ext = first(r, "DebateSectionExtId")
                    title = clean(first(r, "DebateSection") or "")
                    slug = re.sub(r"[^A-Za-z0-9]", "", title.title())
                    out.append({"org": org, "kind": "Debate" if ctype == "Spoken" else "Written statement", "d": date, "house": house,
                                "who": first(r, "AttributedTo", "MemberName"), "mid": first(r, "MemberId"), "t": title, "q": snip,
                                "u": f"https://hansard.parliament.uk/{house}/{date}/debates/{ext}/{slug}" if ext else None,
                                "key": first(r, "ContributionExtId", "ItemId")})
                if len(res) < 50:
                    break
                skip += 50
    return out


def questions(org, names):
    out = []
    for name in names:
        skip = 0
        while skip < 600:
            data = get_json(WQ, {"searchTerm": name, "tabledWhenFrom": START, "take": 50, "skip": skip, "expandMember": "true"}) or {}
            res = data.get("results", [])
            for r in res:
                v = r.get("value", r)
                body = (v.get("questionText") or "") + " " + (v.get("answerText") or "")
                snip = snippet(body, names)
                if not snip:
                    continue
                am = v.get("askingMember") or {}
                out.append({"org": org, "kind": "Written question", "d": (v.get("dateTabled") or "")[:10], "house": v.get("house"),
                            "who": am.get("name"), "p": am.get("partyAbbreviation"), "mid": v.get("askingMemberId"),
                            "t": v.get("heading") or "Written question", "dept": v.get("answeringBodyName"),
                            "q": snip, "inAnswer": bool(snippet(v.get("answerText") or "", names)),
                            "u": f"https://questions-statements.parliament.uk/written-questions/detail/{(v.get('dateTabled') or '')[:10]}/{v.get('uin')}",
                            "key": f"wq{v.get('uin')}"})
            if len(res) < 50:
                break
            skip += 50
    return out


def main():
    allc, counts, months = [], {}, {}
    for org, names in ORGS:
        rows = hansard(org, names) + questions(org, names)
        seen, uniq = set(), []
        for r in sorted(rows, key=lambda r: r["d"], reverse=True):
            k = r.get("key") or (r["d"], r["who"], r["q"][:60])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        counts[org] = len(uniq)
        for r in uniq:
            months.setdefault(org, {}).setdefault(r["d"][:7], 0)
            months[org][r["d"][:7]] += 1
        keep = uniq[:KEEP]
        for r in keep:
            r.pop("key", None)
        allc += keep
    save(os.path.join(DATA, "dash", "citations.json"), {"generated": today().isoformat(), "since": START, "counts": counts,
                                                      "months": months, "items": allc, "orgs": [o for o, _ in ORGS], "names": dict(ORGS)})
    print("citations:", counts)


if __name__ == "__main__":
    main()
