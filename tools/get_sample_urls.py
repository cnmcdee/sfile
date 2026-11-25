#!/usr/bin/env python3
"""get_sample_urls.py — extract the section-2 "Direct Download Links" URLs
from every downloaded fileformat.vpscoder.com task page into one manifest.

Each page's section 2 lists direct download links for example files of
that format, usually as bare text URLs (sometimes <a href>). This script
pulls every http(s) URL out of the section-2 region and emits a JSON
manifest keyed by canonical task number:

    { "845": {"ext": ".XSL", "page": "task-845.html",
              "urls": ["https://raw.githubusercontent.com/.../CDA.xsl", ...]},
      ... }

Duplicate posts for the same task (e.g. task-2 and task-002) are merged:
URL lists are unioned, extension taken from the first page that has one.

Usage:
    ./get_sample_urls.py [pages_dir] [output_json]
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "pages")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRIPT_DIR, "sample_urls.json")

URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")
# Section 2 starts at a "Direct Download Links" heading; it ends at the
# start of section 3/4 (the HTML/JS viewer section) or the next <h2.
SEC2_START = re.compile(r"Direct Download Links", re.I)
SEC_END = re.compile(r"<h2[^>]*>|id=\"3-|id=\"4-|HTML/JavaScript", re.I)
TITLE_RE = re.compile(r"Task\s+(\d+)\s*[:\-]?\s*\.?([A-Za-z0-9]+)", re.I)
EXT_IN_SEC2 = re.compile(r"Direct Download Links for\s+\.?([A-Za-z0-9+]+)", re.I)

def task_no_from_content(s, fname):
    """True task number is inside the page ('Task NNN' title), NOT the
    filename — the wget run named some files by slug and a few are
    misleading (e.g. task-2.html is really Task 161)."""
    m = TITLE_RE.search(s)
    if m:
        return int(m.group(1))
    m = re.match(r"task-(\d+)", fname)
    return int(m.group(1)) if m else None

def clean_url(u):
    # strip trailing punctuation the page text may have glued on
    return u.rstrip(".,;")

manifest = {}
n_pages = 0
for fname in sorted(os.listdir(PAGES_DIR)):
    if not fname.endswith(".html"):
        continue
    n_pages += 1
    path = os.path.join(PAGES_DIR, fname)
    s = open(path, encoding="utf-8", errors="ignore").read()
    t = task_no_from_content(s, fname)
    # extension: from the page <title> / Task NNN .EXT pattern, else section-2 heading
    ext = None
    m = TITLE_RE.search(s)
    if m:
        ext = "." + m.group(2)
    m2 = EXT_IN_SEC2.search(s)
    if m2:
        ext = "." + m2.group(1)
    # section 2 region
    urls = []
    m3 = SEC2_START.search(s)
    if m3:
        rest = s[m3.end():]
        m4 = SEC_END.search(rest)
        if m4:
            rest = rest[:m4.start()]
        urls = [clean_url(u) for u in URL_RE.findall(rest)]
        # dedupe, keep order
        seen = set()
        urls = [u for u in urls if not (u in seen or seen.add(u))]
    entry = manifest.setdefault(str(t), {"ext": ext, "page": fname, "urls": []})
    if ext and not entry["ext"]:
        entry["ext"] = ext
    for u in urls:
        if u not in entry["urls"]:
            entry["urls"].append(u)

with open(OUT, "w") as f:
    json.dump(manifest, f, indent=1, sort_keys=True)
with_urls = sum(1 for v in manifest.values() if v["urls"])
no_urls = sum(1 for v in manifest.values() if not v["urls"])
total_urls = sum(len(v["urls"]) for v in manifest.values())
print(f"pages read: {n_pages}")
print(f"tasks in manifest: {len(manifest)}")
print(f"tasks with >=1 download URL: {with_urls}")
print(f"tasks with NO download URL: {no_urls}")
print(f"total URLs: {total_urls}")
print(f"wrote {OUT}")
print("tasks with no URLs:", sorted(int(k) for k, v in manifest.items() if not v["urls"]))
