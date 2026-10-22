#!/usr/bin/env python3
"""Write data/dash/manifest.json: every document the dashboard database should hold,
with the file it comes from and a fingerprint, so the refresh only copies what changed.

Each entry: {"collection", "doc_id", "file", "sha"}. Files are kept under 240 KB each.
"""
import glob
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import DATA, save, today  # noqa: E402

LIMIT = 240_000


def entry(collection, doc_id, path):
    raw = open(path, "rb").read()
    if len(raw) > LIMIT:
        print(f"  ! {path} is {len(raw)} bytes, over the limit; skipped", file=sys.stderr)
        return None
    return {"collection": collection, "doc_id": doc_id, "file": os.path.relpath(path, os.path.dirname(DATA)),
            "sha": hashlib.sha1(raw).hexdigest()[:12], "bytes": len(raw)}


def main():
    rows = []
    for name, doc in (("trends.json", "trends"), ("emerging.json", "emerging")):
        p = os.path.join(DATA, name)
        if os.path.exists(p):
            rows.append(entry("meta", doc, p))
    for name in ("calendar", "deadlines", "citations", "parties", "bills", "voters"):
        p = os.path.join(DATA, "dash", f"{name}.json")
        if os.path.exists(p):
            rows.append(entry("meta", name, p))
    for p in sorted(glob.glob(os.path.join(DATA, "dash", "profiles-*.json"))):
        rows.append(entry("meta", os.path.basename(p)[:-5], p))
    for p in sorted(glob.glob(os.path.join(DATA, "dash", "bills", "*.json"))):
        rows.append(entry("bills", os.path.basename(p)[:-5], p))
    rows = [r for r in rows if r]
    save(os.path.join(DATA, "dash", "manifest.json"), {"generated": today().isoformat(), "docs": rows}, pretty=True)
    print(f"manifest: {len(rows)} documents, {sum(r['bytes'] for r in rows) // 1024} KB")


if __name__ == "__main__":
    main()
