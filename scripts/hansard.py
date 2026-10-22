#!/usr/bin/env python3
"""Fetch education-related Hansard debates for the Schools & Skills Monitor.

Walks every sitting day in a date range, reads the day's section trees from the
official Hansard API, keeps debates whose title (or a parent title) matches the
education / skills / FE keyword list, and saves each one with its speakers and
contribution text under data/debates/. An index of everything saved is kept in
data/index.json, and the last date processed in data/state.json.

Usage:
  python scripts/hansard.py incremental            # from last processed date - 3 days to today
  python scripts/hansard.py range 2024-07-04 2024-12-31
  python scripts/hansard.py probe 2026-10-13       # saves raw API samples to data/samples/
Standard library only.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

API = "https://hansard-api.parliament.uk"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HOUSES = ["Commons", "Lords"]
SKIP_SECTIONS = {"Correction", "Corrections", "WrittenCorrections"}
DELAY = 0.25

INCLUDE = re.compile(
    r"\b(education\w*|school\w*|pupil\w*|teach\w*|SEND|special educational|"
    r"special needs|send provision|childcare|child care|early years|nurser\w*|"
    r"further education|colleges?|apprentice\w*|skills?|Ofsted|Ofqual|curricul\w*|"
    r"exam\w*|GCSEs?|A[- ]levels?|T[- ]levels?|V[- ]levels?|free school meals|"
    r"breakfast clubs?|academ(y|ies)|multi-academy|home[- ]educat\w*|"
    r"children not in school|school transport|NEETs?|not in education|"
    r"youth guarantee|post-16|16 to 19|sixth form\w*|EHCPs?|"
    r"education, health and care|attendance|exclusions?|RAAC|"
    r"Children's Wellbeing and Schools|Education for All|Skills England|"
    r"Department for Education)\b",
    re.I,
)
# Titles that are clearly out of scope unless they also mention schools/FE/skills.
EXCLUDE = re.compile(
    r"\b(universit\w*|higher education|student loans?|student finance|tuition fees|"
    r"foster\w*|adoption|children's homes|care leavers|social work\w*|children in care|kinship car\w*|"
    r"special guardianship|child protection|children's social care|youth justice|Office for Students)\b",
    re.I,
)
CORE = re.compile(r"\b(school\w*|pupil\w*|further education|colleges?|apprentice\w*|early years|childcare|SEND)\b", re.I)
# Words that make "skills"/"exams" etc. false positives in other contexts.
NOISE = re.compile(r"\b(driving (test|exam)|medical exam\w*|post-mortem|skills? gap in (the )?NHS|School of Art|Mackintosh Building)\b", re.I)


def get(path, params=None, retries=3):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "schools-skills-monitor/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8")
            time.sleep(DELAY)
            return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    print(f"  ! gave up on {url}", file=sys.stderr)
    return None


def first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


PARTIES = {"Lab", "Con", "LD", "CB", "DUP", "Lab/Co-op", "Non-Afl", "Bshp", "SNP", "Green", "PC", "Ind", "Reform", "UUP",
           "SDLP", "Alliance", "TUV", "Restore Britain", "RUK", "Reform UK", "Ind Con", "Ind Lab", "Non-affiliated", "XB", "SF", "UKIP"}
ROLE = re.compile(r"^(The )?(Minister|Parliamentary Under|Secretary of State|Financial Secretary|Chancellor|Lord in Waiting|"
                  r"Baroness in Waiting|Lords? Spokesperson|Solicitor General|Attorney General|Leader of the House|Prime Minister|"
                  r"Deputy|Chair|Speaker|Advocate General|Chief Secretary|Exchequer Secretary|Economic Secretary|Lord Privy Seal)|"
                  r"Minister|Secretary of State|Whip", re.I)


def is_party(g):
    return g in PARTIES or (len(g) <= 10 and " " not in g and g[:1].isupper() and not g.startswith(("Lord", "Mr", "Dr")))


def parse_attribution(w):
    groups = re.findall(r"\(([^()]*)\)", w)
    head = re.sub(r"\s*\([^()]*\)", "", w).strip()
    name = role = party = seat = None
    if head.lower() in ("the chair", "the chairman", "the deputy speaker", "mr speaker", "madam deputy speaker", "the lord speaker", "the deputy chairman of committees"):
        return None, "Chair", None, None
    if ROLE.search(head):
        role = head
    else:
        name = head
    rest = []
    for g in groups:
        if g.lower().startswith("in the chair"):
            role = "Chair"
        else:
            rest.append(g)
    if rest and is_party(rest[-1]):
        party = rest.pop()
    for g in rest:
        if name is None:
            name = g
        else:
            seat = g
    return name, role, party, seat


def walk_tree(node, ancestors, out):
    """Collect (title, external id, ancestor titles) for every node in a section tree."""
    if isinstance(node, list):
        for n in node:
            walk_tree(n, ancestors, out)
        return
    if not isinstance(node, dict):
        return
    items = node.get("SectionTreeItems")
    if isinstance(items, list):
        # Flat list linked by ParentId: rebuild each item's chain of parent titles.
        byid = {i.get("Id"): i for i in items if isinstance(i, dict)}
        for i in items:
            if not isinstance(i, dict) or not i.get("Title"):
                continue
            chain, p, guard = [], i.get("ParentId"), 0
            while p in byid and guard < 20:
                chain.insert(0, strip_html(byid[p].get("Title", "")))
                p, guard = byid[p].get("ParentId"), guard + 1
            out.append({"title": strip_html(i["Title"]), "ext": i.get("ExternalId"), "anc": ancestors + chain})
        return
    title = first(node, "Title", "title", "SectionTitle", "Name")
    ext = first(node, "ExternalId", "ExtId", "DebateSectionExtId", "externalId")
    here = ancestors
    if title:
        out.append({"title": strip_html(str(title)), "ext": ext, "anc": list(ancestors)})
        here = ancestors + [strip_html(str(title))]
    for v in node.values():
        if isinstance(v, (list, dict)):
            walk_tree(v, here, out)


def relevant(title, anc):
    text = " / ".join(anc + [title])
    if NOISE.search(text):
        return False
    if not INCLUDE.search(text):
        return False
    if EXCLUDE.search(text) and not CORE.search(text):
        return False
    return True


def contributions(debate):
    """Pull speaker contributions out of a debate document, whatever its exact shape."""
    out = []

    def rec(n):
        if isinstance(n, list):
            for x in n:
                rec(x)
            return
        if not isinstance(n, dict):
            return
        who = first(n, "AttributedTo", "attributedTo", "MemberName")
        val = first(n, "Value", "value", "Text", "ContributionText")
        if who and val:
            out.append({
                "who": strip_html(str(who)),
                "member_id": first(n, "MemberId", "memberId"),
                "type": first(n, "ItemType", "itemType"),
                "text": strip_html(str(val))[:1200],
            })
        for v in n.values():
            if isinstance(v, (list, dict)):
                rec(v)

    rec(debate)
    # Hansard gives "Name (Constituency) (Party)" on a member's first contribution
    # and just the name afterwards: carry the full attribution forward by member id.
    # Attributions come as "Name (Seat) (Party)", "Name (Party)", "Role (Name) (Party)",
    # "Name (in the Chair)" or a bare name/role on later contributions. Resolve each
    # member id to its most common name and party.
    people = {}
    for c in out:
        name, role, party, seat = parse_attribution(c["who"])
        key = c.get("member_id") or c["who"]
        p = people.setdefault(key, {"names": Counter(), "parties": Counter(), "seats": Counter(), "roles": Counter()})
        if name: p["names"][name] += 1
        if party: p["parties"][party] += 1
        if seat: p["seats"][seat] += 1
        if role: p["roles"][role] += 1
    for c in out:
        p = people[c.get("member_id") or c["who"]]
        c["name"] = p["names"].most_common(1)[0][0] if p["names"] else (p["roles"].most_common(1)[0][0] if p["roles"] else c["who"])
        for k, src in (("party", "parties"), ("seat", "seats"), ("role", "roles")):
            if p[src]:
                c[k] = p[src].most_common(1)[0][0]
    return [c for c in out if c.get("member_id") or c["who"] not in ("Hon. Members", "Several hon. Members")]


def subtitles(debate):
    out = []
    def rec(n):
        for ch in (n.get("ChildDebates") or []) if isinstance(n, dict) else []:
            t = first(first(ch, "Overview") or {}, "Title")
            if t:
                out.append(strip_html(str(t)))
            rec(ch)
    rec(debate)
    return out


def debate_meta(debate):
    ov = first(debate, "Overview", "overview") or {}
    return {
        "title": strip_html(str(first(ov, "Title", "title") or "")),
        "location": first(ov, "Location", "location", "HRSTag"),
        "house": first(ov, "House", "house"),
        "date": first(ov, "Date", "date"),
    }


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def store(debate, ext, day, house, section, title, anc, index):
    """Save one debate file and add or replace its index entry."""
    meta = debate_meta(debate)
    contribs = contributions(debate)
    speakers, seen_names = [], set()
    for c in contribs:
        if c.get("name") and c["name"] not in seen_names:
            seen_names.add(c["name"])
            speakers.append({k: c.get(k) for k in ("name", "party", "seat", "role", "member_id") if c.get(k)})
    title = meta["title"] or title
    rec = {
        "ext_id": ext, "date": day, "house": house, "section": section, "title": title, "parents": anc,
        "location": meta["location"],
        "url": f"https://hansard.parliament.uk/{house}/{day}/debates/{ext}/{re.sub(r'[^A-Za-z0-9]', '', title.title())}",
        "subtitles": subtitles(debate), "speakers": speakers, "contributions": contribs,
        "fetched": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    rel = os.path.join("debates", day[:4], f"{day}-{house}-{ext}.json")
    save(os.path.join(DATA, rel), rec)
    index[:] = [r for r in index if not (r["house"] == house and r["ext_id"] == ext)]
    index.append({"date": day, "house": house, "section": section, "title": title, "parents": anc,
                  "subtitles": rec["subtitles"][:40], "ext_id": ext, "file": "data/" + rel,
                  "speakers": len(speakers), "contributions": len(contribs), "fetched": rec["fetched"]})


def rebuild():
    """Refetch every debate already in the index and re-save it with the current parser."""
    index_path = os.path.join(DATA, "index.json")
    index = load(index_path, [])
    for r in list(index):
        debate = get(f"/debates/debate/{r['ext_id']}.json")
        if debate is not None:
            store(debate, r["ext_id"], r["date"], r["house"], r["section"], r["title"], r.get("parents", []), index)
    index.sort(key=lambda r: (r["date"], r["house"], r["title"]))
    save(index_path, index)
    print(f"rebuilt {len(index)} debates")


def process_day(day, index, seen, probe=False):
    found = 0
    for house in HOUSES:
        sections = get("/overview/sectionsforday.json", {"date": day, "house": house})
        if probe:
            save(os.path.join(DATA, "samples", f"sectionsforday-{house}-{day}.json"), sections)
        if not sections:
            continue
        names = [s if isinstance(s, str) else first(s, "Name", "Section", "name") for s in (sections if isinstance(sections, list) else [sections])]
        for section in [n for n in names if n and n not in SKIP_SECTIONS]:
            tree = get("/overview/sectiontrees.json", {"section": section, "date": day, "house": house})
            if probe:
                save(os.path.join(DATA, "samples", f"sectiontrees-{house}-{section}-{day}.json"), tree)
            nodes = []
            walk_tree(tree, [], nodes)
            taken_titles = []
            for n in nodes:
                if not n["ext"] or not relevant(n["title"], n["anc"]):
                    continue
                # Skip children of a node already taken (a whole questions session, say).
                if any(t in n["anc"] for t in taken_titles):
                    continue
                key = f"{house}|{n['ext']}"
                if key in seen:
                    continue
                debate = get(f"/debates/debate/{n['ext']}.json")
                if debate is None:
                    continue
                if probe and found == 0:
                    save(os.path.join(DATA, "samples", f"debate-{n['ext']}.json"), debate)
                store(debate, n["ext"], day, house, section, n["title"], n["anc"], index)
                seen.add(key)
                taken_titles.append(n["title"])
                found += 1
    return found


def run(start, end, probe=False):
    index_path = os.path.join(DATA, "index.json")
    state_path = os.path.join(DATA, "state.json")
    index = load(index_path, [])
    # Hansard publishes a rolling record that is finalised later, so recent days are re-read.
    recent = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    seen = {f"{r['house']}|{r['ext_id']}" for r in index if r["date"] < recent}
    d = dt.date.fromisoformat(start)
    stop = dt.date.fromisoformat(end)
    total = 0
    while d <= stop:
        if d.weekday() < 6:  # Parliament rarely sits on Sundays
            n = process_day(d.isoformat(), index, seen, probe)
            if n:
                print(f"{d}: {n} debates")
            total += n
            if not probe:
                index.sort(key=lambda r: (r["date"], r["house"], r["title"]))
                save(index_path, index)
                st = load(state_path, {})
                if d.isoformat() > st.get("last_date", ""):
                    st["last_date"] = d.isoformat()
                st["updated"] = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                save(state_path, st)
        d += dt.timedelta(days=1)
    print(f"done: {total} new debates between {start} and {end}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "incremental"
    today = dt.date.today()
    if mode == "rebuild":
        rebuild()
    elif mode == "probe":
        day = sys.argv[2] if len(sys.argv) > 2 else (today - dt.timedelta(days=1)).isoformat()
        run(day, day, probe=True)
    elif mode == "range":
        run(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else today.isoformat())
    else:
        st = load(os.path.join(DATA, "state.json"), {})
        last = st.get("last_date")
        start = (dt.date.fromisoformat(last) - dt.timedelta(days=3)).isoformat() if last else (today - dt.timedelta(days=14)).isoformat()
        run(start, today.isoformat())
