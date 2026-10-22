#!/usr/bin/env python3
"""Fetch education media with a continuous history since July 2024.

Sources a GitHub runner can read openly:
  - GOV.UK news and communications from the Department for Education (search API)
  - FE News (WordPress REST API, falling back to its RSS feed)
Schools Week, FE Week and Tes block automated readers, so their headlines are added
to data/media/press.json by the dashboard refresh instead.

Writes data/media/govuk.json and data/media/fenews.json as lists of
  {"d": date, "t": title, "u": url, "s": source} (GOV.UK items also keep their Open Government Licence summary as "x";
  FE News items keep only the headline and link)
Standard library only.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "media")
START = "2024-07-04"
UA = "education-monitor/1.0 (+https://github.com/doodledowndesigns/Monitor)"


def fetch(url, accept="application/json", retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
            time.sleep(0.6)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                print(f"  {e.code} {url}", file=sys.stderr)
                return None
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return None


def clean(s, n=300):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()[:n]


def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return []


def save(path, rows):
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["d"], r["u"]), reverse=True):
        if r["u"] in seen or r["d"] < START:
            continue
        seen.add(r["u"])
        out.append(r)
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(out)


def govuk():
    path = os.path.join(OUT, "govuk.json")
    rows = load(path)
    since = START if not rows else (dt.date.fromisoformat(max(r["d"] for r in rows)) - dt.timedelta(days=7)).isoformat()
    start = 0
    while True:
        q = {"filter_organisations": "department-for-education", "filter_content_purpose_supergroup": "news_and_communications",
             "filter_public_timestamp": f"from:{since}", "count": 500, "start": start, "order": "-public_timestamp",
             "fields": "title,link,public_timestamp,content_store_document_type,description"}
        body = fetch("https://www.gov.uk/api/search.json?" + urllib.parse.urlencode(q))
        if not body:
            break
        data = json.loads(body)
        res = data.get("results", [])
        for r in res:
            rows.append({"d": (r.get("public_timestamp") or "")[:10], "t": clean(r.get("title"), 200),
                         "u": "https://www.gov.uk" + r.get("link", ""), "x": clean(r.get("description")),
                         "s": "GOV.UK (DfE)", "k": r.get("content_store_document_type")})
        start += len(res)
        if not res or start >= data.get("total", 0):
            break
    print(f"govuk: {save(path, rows)} items")


def fenews():
    path = os.path.join(OUT, "fenews.json")
    rows = load(path)
    known = {r["u"] for r in rows}
    since = START if not rows else (dt.date.fromisoformat(max(r["d"] for r in rows)) - dt.timedelta(days=3)).isoformat()
    added, page, rest_ok = 0, 1, True
    while page <= 400:
        url = "https://www.fenews.co.uk/wp-json/wp/v2/posts?" + urllib.parse.urlencode(
            {"per_page": 100, "page": page, "after": since + "T00:00:00", "_fields": "date,link,title,excerpt", "orderby": "date", "order": "desc"})
        body = fetch(url)
        if body is None:
            rest_ok = page > 1
            break
        try:
            res = json.loads(body)
        except Exception:
            rest_ok = page > 1
            break
        if not isinstance(res, list) or not res:
            break
        for r in res:
            u = r.get("link")
            if u and u not in known:
                known.add(u)
                rows.append({"d": (r.get("date") or "")[:10], "t": clean((r.get("title") or {}).get("rendered"), 200), "u": u, "s": "FE News"})
                added += 1
        page += 1
    if not rest_ok:
        print("  fenews: REST unavailable, using RSS", file=sys.stderr)
        page = 1
        while page <= 900:
            body = fetch(f"https://www.fenews.co.uk/feed/?paged={page}", accept="application/rss+xml")
            if not body:
                break
            try:
                root = ET.fromstring(body)
            except Exception:
                break
            items = root.findall(".//item")
            if not items:
                break
            oldest = "9999"
            for it in items:
                u = (it.findtext("link") or "").strip()
                try:
                    d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
                except Exception:
                    continue
                oldest = min(oldest, d)
                if u and u not in known:
                    known.add(u)
                    rows.append({"d": d, "t": clean(it.findtext("title"), 200), "u": u, "s": "FE News"})
                    added += 1
            if oldest < since:
                break
            page += 1
    print(f"fenews: {save(path, rows)} items ({added} new)")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    govuk()
    fenews()
    press = os.path.join(OUT, "press.json")
    if not os.path.exists(press):
        with open(press, "w") as f:
            json.dump([], f)
