#!/usr/bin/env python3
"""Work out which education issues are rising or falling in Parliament and the media.

Reads every source the repo holds:
  Parliament: data/questions/*.json (DfE written questions), data/index.json (Hansard
              debates, statements and each oral question in a questions session)
  Media:      data/media/govuk.json, data/media/fenews.json, data/media/press.json
Classifies each item into the dashboard's topics, then for 7, 30, 90 and 365 days
compares the latest period with the one before it. A media source only counts in a
comparison if its history covers both periods, so a newly added outlet never shows up
as a false surge. Also finds breakout terms: words and phrases appearing far more
often than in the previous period.

Writes data/emerging.json.
"""
import datetime as dt
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hansard import relevant, INCLUDE, EXCLUDE, CORE  # noqa: E402
from trends import COMPILED  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
START = "2024-07-04"
PERIODS = [7, 30, 90, 365]
MIN_TERM = {7: 4, 30: 6, 90: 10, 365: 18}

STOP = set("""a about above across after again against all almost also although always am among an and any are around as at be because been before
being below between both but by can could did do does doing done down during each either else enough even ever every few for from further had has
have having he her here hers herself him himself his how however i if in into is it its itself just last least less like made make many may me might
more most much must my near need needs new no nor not now of off often on once one only or other our out over own per perhaps rather really same
several shall she should since so some still such than that the their them themselves then there these they this those though through to too under
until up upon us very via was we well were what when where whether which while who whom whose why will with within without would yet you your
ask asks asked answer answers answered question questions tabled hon member members house lords commons lord baroness minister ministers secretary
state department departments government governments steps taking take taken assessment assessments made make making plan plans planning policy
policies ensure ensuring support supporting supported provide providing provided improve improving help helping access number numbers proportion
level levels data recent potential merits impact impacts effect effects current currently publish published publication estimate estimates
discussions discussion including include includes reference pursuant regard regarding relation respect consider considered considering
school schools pupil pupils student students education educational child children young people person learner learners family families parents
england uk national local authority authorities area areas council councils year years month months week weeks day days today time number
january february march april may june july august september october november december 2023 2024 2025 2026 2027 2028
sector sectors service services system systems work working provision provisions need needed programme programmes support new news says said
mr mrs ms dr sir dame rt hon mp mps peer peers what's it's government's department's
press release entitled published joint findings study post office awards award age results interest reforms reform partnership
adult jobs job college colleges skills skill technical britain british vital role threshold launch launches launched calls call
warns warn urges urge sets set plan plans says week latest guide guidance report reports review reviews research""".split())
BOILER = re.compile(r"\b(what steps (she|he|they|the Government|her Department|his Department) (is|are|has|have) taken?( to)?|"
                    r"what assessment (she|he|they|her Department) (has|have) made of|with reference to|pursuant to the answer of|"
                    r"if (she|he) will (make a statement|publish)|whether (she|he|they) (has|have|will)|her Department|his Department|"
                    r"His Majesty's Government|the Secretary of State for Education)\b", re.I)


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def topics(text):
    return [t for t, rx in COMPILED if rx.search(text)]


HE_CARE = re.compile(r"^(Students?|Universities|Higher Education|Student Loans Company|Postgraduate|Graduates?|Social Workers?|"
                     r"Children in Care|Foster\w*|Adoption|Kinship Care|Care Leavers|Children: Social Services|"
                     r"Children's Social Care|Social Services|Special Guardianship|Youth Justice)\b", re.I)


def out_of_scope(text):
    if HE_CARE.search(text or ""):
        return True
    return bool(EXCLUDE.search(text)) and not CORE.search(text)


def units():
    """Every in-scope item as {d, src (p|m), s (source name), t, u, text, tp}."""
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "questions", "*.json"))):
        for r in load(f, []):
            if r.get("w") or not r.get("d"):
                continue
            head = r.get("hd") or ""
            q = BOILER.sub(" ", r.get("q") or "")
            if out_of_scope(head or q[:160]):
                continue
            text = f"{head}. {q}"
            out.append({"d": r["d"], "src": "p", "s": "Written questions", "t": head or q[:90].strip(" ,."), "hd": head,
                        "u": f"https://questions-statements.parliament.uk/written-questions/detail/{r['d']}/{r['uin']}",
                        "text": text, "tp": topics(text)})
    for r in load(os.path.join(DATA, "index.json"), []):
        if not relevant(r["title"], r.get("parents") or []):
            continue
        slug = re.sub(r"[^A-Za-z0-9]", "", r["title"].title())
        url = f"https://hansard.parliament.uk/{r['house']}/{r['date']}/debates/{r['ext_id']}/{slug}"
        subs = [s for s in (r.get("subtitles") or []) if s and s.lower() not in ("topical questions", "written statements", "education")]
        kind = "Statements" if r.get("section") == "WMS" else "Debates"
        if subs:
            for s in subs:
                if out_of_scope(s):
                    continue
                out.append({"d": r["date"], "src": "p", "s": kind, "t": s, "u": url, "text": s, "tp": topics(s)})
        else:
            text = " / ".join((r.get("parents") or [])[-1:] + [r["title"]])
            out.append({"d": r["date"], "src": "p", "s": kind, "t": r["title"], "u": url, "text": r["title"], "tp": topics(text)})
    for name in ("govuk", "fenews", "press"):
        for r in load(os.path.join(DATA, "media", f"{name}.json"), []):
            title, desc = r.get("t") or "", (r.get("x") or "")[:180]
            full = f"{title}. {desc}"
            if not r.get("d") or not INCLUDE.search(full) or out_of_scope(title):
                continue
            out.append({"d": r["d"], "src": "m", "s": r.get("s") or name, "t": title, "u": r.get("u"), "text": title, "tp": topics(full)})
    return [u for u in out if u["d"] >= START]


def tokens(text, heading=None):
    text = re.sub(r"\b([TVA])[\s-][Ll]evels?\b", r"\1-levels", text)
    grams = {}
    if heading and ":" in heading and not re.match(r"(Department for Education|Members|Parliamentary Questions)\b", heading):
        grams["h:" + heading.lower()] = heading
    for seg in re.split(r"[:;,.?!()\[\]\"“”]+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*[A-Za-z]|[A-Z]", seg)
        keys = [(w.lower().replace("’", "'"), w) for w in words]
        seg_grams(keys, grams)
    return grams


def seg_grams(keys, grams):
    for i, (k, w) in enumerate(keys):
        # Single words only when they are acronyms or hyphenated terms (RAAC, SEND, V-levels).
        if k not in STOP and len(k) >= 3 and ((w.isupper() and len(w) >= 3) or "-" in w):
            grams.setdefault(k, w)
        if i + 1 < len(keys):
            k2, w2 = keys[i + 1]
            if k not in STOP and k2 not in STOP and len(k) >= 3 and len(k2) >= 3:
                grams.setdefault(k + " " + k2, w + " " + w2)
    return grams


def g2(c, p, nc, npv):
    """Log-likelihood ratio for a term seen c times in nc docs versus p times in npv docs."""
    e1 = nc * (c + p) / (nc + npv)
    e2 = npv * (c + p) / (nc + npv)
    s = 0.0
    for o, e in ((c, e1), (p, e2)):
        if o > 0 and e > 0:
            s += o * math.log(o / e)
    return 2 * s


def main():
    # Written questions appear in the API a day or two after tabling, so periods end yesterday.
    today = dt.date.today() - dt.timedelta(days=1)
    U = units()
    # When each media source's history begins.
    starts = {}
    for u in U:
        if u["src"] == "m":
            starts[u["s"]] = min(starts.get(u["s"], "9999"), u["d"])
    day = lambda n: (today - dt.timedelta(days=n)).isoformat()
    names = [t for t, _ in COMPILED]
    result = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "end": today.isoformat(),
              "media_sources": [{"name": k, "from": v} for k, v in sorted(starts.items(), key=lambda kv: kv[1])], "periods": {}}
    for P in PERIODS:
        cs, ce, ps, pe = day(P - 1), today.isoformat(), day(2 * P - 1), day(P)
        ok_media = {k for k, v in starts.items() if v <= ps}
        use = lambda u: u["src"] == "p" or u["s"] in ok_media
        cur = [u for u in U if cs <= u["d"] <= ce and use(u)]
        prv = [u for u in U if ps <= u["d"] <= pe and use(u)]
        tot = {"p": [sum(1 for u in cur if u["src"] == "p"), sum(1 for u in prv if u["src"] == "p")],
               "m": [sum(1 for u in cur if u["src"] == "m"), sum(1 for u in prv if u["src"] == "m")]}
        rows = []
        for t in names:
            row = {"id": t}
            for s in ("p", "m"):
                row[s] = [sum(1 for u in cur if u["src"] == s and t in u["tp"]), sum(1 for u in prv if u["src"] == s and t in u["tp"])]
            rows.append(row)
        # Breakout terms
        dc, dp = Counter(), Counter()
        disp, where, examples, docs = {}, defaultdict(Counter), defaultdict(list), defaultdict(set)
        for ui, u in enumerate(sorted(cur, key=lambda u: u["d"], reverse=True)):
            g = tokens(u["text"], u.get("hd"))
            for k, w in g.items():
                dc[k] += 1
                docs[k].add(ui)
                disp.setdefault(k, Counter())[w] += 1
                where[k][u["src"]] += 1
                if len(examples[k]) < 6:
                    examples[k].append(u)
        for u in prv:
            for k in tokens(u["text"], u.get("hd")):
                dp[k] += 1
        nc, npv = max(1, len(cur)), max(1, len(prv))
        cands = []
        for k, c in dc.items():
            if c < MIN_TERM[P]:
                continue
            p = dp.get(k, 0)
            ratio = ((c + .5) / nc) / ((p + .5) / npv)
            if ratio < 2.2:
                continue
            cands.append((g2(c, p, nc, npv) * (1.3 if k.startswith("h:") else 1), k, c, p))
        cands.sort(reverse=True)
        chosen = []
        for sc, k, c, p in cands:
            # Skip a term that mostly appears in the same items as one already chosen (one campaign, many phrases).
            if any(len(docs[k] & docs[ck]) >= 0.6 * min(len(docs[k]), len(docs[ck])) for _, ck, _, _ in chosen):
                continue
            chosen.append((sc, k, c, p))
            if len(chosen) >= 12:
                break
        terms = []
        for sc, k, c, p in chosen[:12]:
            ex, seen_src = [], set()
            for u in examples[k]:
                if u["src"] in seen_src and len(examples[k]) > 2 and len(ex) < 2:
                    continue
                seen_src.add(u["src"])
                ex.append({"t": u["t"][:140], "d": u["d"], "u": u["u"], "s": u["s"]})
                if len(ex) >= 3:
                    break
            terms.append({"term": disp[k].most_common(1)[0][0], "kind": "heading" if k.startswith("h:") else "phrase", "c": c, "prev": p, "p": where[k]["p"], "m": where[k]["m"], "ex": ex})
        result["periods"][str(P)] = {"cur": [cs, ce], "prev": [ps, pe], "media_sources": sorted(ok_media),
                                    "totals": tot, "topics": rows, "terms": terms}
    # Weekly series for sparklines: last 26 weeks, ending today.
    wk_media = {k for k, v in starts.items() if v <= day(26 * 7 - 1)}
    weeks = [(day(7 * (25 - i) + 6), day(7 * (25 - i))) for i in range(26)]
    spark = {t: {"p": [0] * 26, "m": [0] * 26} for t in names}
    totals_w = {"p": [0] * 26, "m": [0] * 26}
    for u in U:
        if u["src"] == "m" and u["s"] not in wk_media:
            continue
        for i, (a, b) in enumerate(weeks):
            if a <= u["d"] <= b:
                totals_w[u["src"]][i] += 1
                for t in u["tp"]:
                    if t in spark:
                        spark[t][u["src"]][i] += 1
                break
    result["weeks"] = {"start": weeks[0][0], "end": weeks[-1][1], "media_sources": sorted(wk_media), "topics": spark, "totals": totals_w}
    result["counts"] = {"parliament": sum(1 for u in U if u["src"] == "p"), "media": sum(1 for u in U if u["src"] == "m")}
    with open(os.path.join(DATA, "emerging.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"emerging: {len(U)} items; media sources {starts}")


if __name__ == "__main__":
    main()
