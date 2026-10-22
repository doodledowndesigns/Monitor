"""Small shared helpers for the Education Monitor fetchers (standard library only)."""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "education-monitor/1.0 (+https://github.com/doodledowndesigns/Monitor)"
START = "2024-07-04"


def get_json(url, params=None, retries=3, delay=0.25, quiet404=True):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read().decode("utf-8")
            time.sleep(delay)
            return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            if e.code in (400, 404) and quiet404:
                return None
            print(f"  HTTP {e.code} {url}", file=sys.stderr)
            if e.code in (401, 403):
                return None
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  retry {attempt + 1} {url}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj, pretty=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def today():
    return dt.date.today()


def d10(s):
    return (s or "")[:10] or None
