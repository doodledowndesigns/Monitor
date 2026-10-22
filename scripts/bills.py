#!/usr/bin/env python3
"""Bill tracker: education bills since the 2024 election, their stages, amendments and votes.

Finds bills two ways: names of bills debated in the saved Hansard index, and a search of
the Bills API for education terms. For each bill: title, sponsor, current stage, every
stage with its sitting dates, amendment counts per stage, and every Commons and Lords
division on it with how each member voted. Writes data/dash/bills/<billId>.json, a
summary list in data/dash/bills.json and a member lookup in data/dash/voters.json.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, START, get_json, first, load, save, today  # noqa: E402

BILLS = "https://bills-api.parliament.uk/api/v1"
CVOTES = "https://commonsvotes-api.parliament.uk/data"
LVOTES = "https://lordsvotes-api.parliament.uk/data"
TERMS = ["school", "education", "skills", "apprentice", "childcare", "special educational", "curriculum", "teacher",
         "further education", "free school meals", "children's wellbeing", "academ"]
EXCLUDE = re.compile(r"universit|higher education|student|social work|adoption|foster", re.I)
EDUCATION = re.compile(r"school|educat|pupil|teacher|curricul|apprentice|skills|childcare|early years|nurser|"
                       r"special educational|SEND\b|college|academ|free school meals|young carers|children not in school", re.I)


def norm(t):
    t = re.sub(r"\s*\[(HL|Lords)\]", "", t or "").replace("\u2019", "'")
    t = re.sub(r"\s+Act( \d{4})?$", " Bill", t)
    return re.sub(r"\s+", " ", t).strip()


def b36(n):
    s, n = "", int(n)
    while True:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
        if n == 0:
            return s


def candidates():
    names = set()
    for r in load(os.path.join(DATA, "index.json"), []):
        m = re.search(r"^(.*? Bill)(?: \[(?:HL|Lords)\])?", r["title"])
        if m:
            names.add(m.group(1))
    found = {}
    for q in sorted(names) + TERMS:
        data = get_json(f"{BILLS}/Bills", {"SearchTerm": q, "Take": 50, "SortOrder": "DateUpdatedDescending"}) or {}
        for b in data.get("items", []):
            if (b.get("lastUpdate") or "") < START:
                continue
            if EXCLUDE.search(b.get("shortTitle", "")) or not EDUCATION.search(b.get("shortTitle", "")):
                continue
            found[b["billId"]] = b
    # The same private member's bill is often reintroduced each session: keep the newest
    newest = {}
    for bid, b in found.items():
        k = norm(b.get("shortTitle")).lower()
        if k not in newest or (b.get("lastUpdate") or "") > (found[newest[k]].get("lastUpdate") or ""):
            newest[k] = bid
    return {bid: found[bid] for bid in newest.values()}


def matches(title, base):
    t = (title or "").replace("\u2019", "'").lower()
    return base.lower() in t and not t.startswith("draft ")


def search_term(base):
    # Search on the part after any possessive, as titles mix curly and straight apostrophes
    return re.sub(r"^.*?'s\s+", "", base)


def stages(bid):
    data = get_json(f"{BILLS}/Bills/{bid}/Stages", {"Take": 100}) or {}
    out = []
    for s in data.get("items", []):
        sits = sorted({(x.get("date") or "")[:10] for x in s.get("stageSittings") or [] if x.get("date")})
        amend = None
        if re.search(r"committee|report|consideration|amendment", s.get("description", ""), re.I):
            a = get_json(f"{BILLS}/Bills/{bid}/Stages/{s['id']}/Amendments", {"Take": 1}) or {}
            amend = a.get("totalResults")
        out.append({"id": s["id"], "stage": s.get("description"), "house": s.get("house"), "dates": sits, "amendments": amend, "order": s.get("sortOrder")})
    out.sort(key=lambda s: (s["dates"][0] if s["dates"] else "9999", s["order"] or 0))
    return out


def commons_divisions(title, voters):
    out, skip = [], 0
    while True:
        res = get_json(f"{CVOTES}/divisions.json/search", {"queryParameters.searchTerm": search_term(title), "queryParameters.startDate": START,
                                                           "queryParameters.take": 25, "queryParameters.skip": skip})
        if not res:
            break
        for d in res:
            if not matches(d.get("Title"), title):
                continue
            det = get_json(f"{CVOTES}/division/{d['DivisionId']}.json") or d
            ayes, noes = det.get("Ayes") or [], det.get("Noes") or []
            for m in ayes + noes:
                voters[str(m["MemberId"])] = [m.get("Name"), m.get("PartyAbbreviation") or m.get("Party"), "Commons"]
            out.append({"id": f"c{d['DivisionId']}", "house": "Commons", "d": (det.get("Date") or "")[:10], "n": det.get("Number"),
                        "t": det.get("Title"), "aye": det.get("AyeCount"), "no": det.get("NoCount"),
                        "ayes": ",".join(b36(m["MemberId"]) for m in ayes), "noes": ",".join(b36(m["MemberId"]) for m in noes),
                        "u": f"https://votes.parliament.uk/votes/commons/division/{d['DivisionId']}"})
        if len(res) < 25:
            break
        skip += 25
    return out


def lords_divisions(title, voters):
    out, skip = [], 0
    while True:
        res = get_json(f"{LVOTES}/Divisions/search", {"SearchTerm": search_term(title), "StartDate": START, "Take": 25, "Skip": skip})
        if not res:
            break
        for d in res:
            if not matches(first(d, "title", "Title"), title):
                continue
            did = first(d, "divisionId", "DivisionId")
            det = get_json(f"{LVOTES}/Divisions/{did}") or d
            con, nc = det.get("contents") or [], det.get("notContents") or []
            for m in con + nc:
                voters[str(m["memberId"])] = [m.get("name"), m.get("party"), "Lords"]
            out.append({"id": f"l{did}", "house": "Lords", "d": (first(det, "date") or "")[:10], "n": first(det, "number"),
                        "t": first(det, "title"), "aye": first(det, "contentCount", "authoritativeContentCount"),
                        "no": first(det, "notContentCount", "authoritativeNotContentCount"),
                        "ayes": ",".join(b36(m["memberId"]) for m in con), "noes": ",".join(b36(m["memberId"]) for m in nc),
                        "u": f"https://votes.parliament.uk/votes/lords/division/{did}"})
        if len(res) < 25:
            break
        skip += 25
    return out


def main():
    found = candidates()
    voters = load(os.path.join(DATA, "dash", "voters.json"), {}) or {}
    summary = []
    for bid, b in sorted(found.items(), key=lambda kv: kv[1].get("lastUpdate", ""), reverse=True):
        det = get_json(f"{BILLS}/Bills/{bid}") or b
        st = stages(bid)
        short = det.get("shortTitle") or b.get("shortTitle")
        base = norm(short)
        divs = commons_divisions(base, voters) + lords_divisions(base, voters)
        divs.sort(key=lambda d: d["d"])
        sponsors = []
        for s in det.get("sponsors") or []:
            mem = s.get("member") or {}
            org = s.get("organisation") or {}
            sponsors.append({"n": mem.get("name"), "p": mem.get("party"), "org": org.get("name")})
        cur = det.get("currentStage") or {}
        rec = {"id": bid, "t": short, "long": det.get("longTitle"), "summary": re.sub(r"<[^>]+>", " ", det.get("summary") or "").strip()[:600] or None,
               "type": "Government" if any(s.get("org") for s in sponsors) else "Private member's",
               "sponsors": sponsors, "house": det.get("currentHouse"), "origin": det.get("originatingHouse"),
               "stage": cur.get("description"), "stageHouse": cur.get("house"), "updated": (det.get("lastUpdate") or "")[:10],
               "act": bool(det.get("isAct")), "withdrawn": bool(det.get("billWithdrawn")), "defeated": bool(det.get("isDefeated")),
               "u": f"https://bills.parliament.uk/bills/{bid}", "stages": st, "divisions": divs,
               "session": max(det.get("includedSessionIds") or [0])}
        path = os.path.join(DATA, "dash", "bills", f"{bid}.json")
        for old in [f for f in os.listdir(os.path.dirname(path))] if os.path.isdir(os.path.dirname(path)) else []:
            if old.startswith(f"{bid}-votes-"):
                os.remove(os.path.join(os.path.dirname(path), old))
        size = len(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        if size > 200_000:
            parts, cur, n = [], [], 0
            for d in divs:
                b = len(json.dumps(d, separators=(",", ":")))
                if cur and n + b > 180_000:
                    parts.append(cur)
                    cur, n = [], 0
                cur.append(d)
                n += b
            if cur:
                parts.append(cur)
            for i, part in enumerate(parts, 1):
                save(os.path.join(DATA, "dash", "bills", f"{bid}-votes-{i}.json"), {"bill": bid, "part": i, "divisions": part})
            rec = rec | {"divisions": [{k: v for k, v in d.items() if k not in ("ayes", "noes")} for d in divs], "voteParts": len(parts)}
        save(path, rec)
        summary.append({k: rec[k] for k in ("id", "t", "type", "sponsors", "house", "stage", "stageHouse", "updated", "act", "withdrawn", "defeated", "u", "session")}
                       | {"divisions": len(divs), "next": next((s for s in st if s["dates"] and s["dates"][-1] >= rec["updated"]), None)})
    # A bill that is not an Act and was not carried into the latest session fell when its session ended
    current = max([s["session"] for s in summary] or [0])
    for s in summary:
        s["fell"] = not (s["act"] or s["withdrawn"] or s["defeated"]) and s["session"] < current
    save(os.path.join(DATA, "dash", "bills.json"), {"generated": today().isoformat(), "items": summary})
    save(os.path.join(DATA, "dash", "voters.json"), voters)
    keep = {str(s["id"]) for s in summary}
    bdir = os.path.join(DATA, "dash", "bills")
    for f in os.listdir(bdir):  # bills no longer in the list (e.g. older duplicates)
        if f.split("-")[0].removesuffix(".json") not in keep:
            os.remove(os.path.join(bdir, f))
    print(f"bills: {len(summary)} bills, {sum(s['divisions'] for s in summary)} divisions, {len(voters)} voters")


if __name__ == "__main__":
    main()
