#!/usr/bin/env python3
"""bulk_fetch.py — fast bulk download of sample files from the task pages'
"Direct Download Links" (tools/sample_urls.json).

This is the scripted, parallel counterpart to the per-range collector
agents: it tries each task's manifest URLs in order and saves the first
one that downloads cleanly. It does NOT do web searches — the collector
agents handle the fallback for tasks whose page links are all dead.

A download counts as clean only if the file is non-empty and is not an
HTML error page (first bytes are not <html / <!DOCTYPE / <head).

Usage:
    ./bulk_fetch.py [sample_urls.json] [samples_dir] [jobs]
Defaults: tools/sample_urls.json, samples/, 8 parallel workers.
Skips tasks whose sample file already exists. Writes a JSON report of
what it fetched (or failed to fetch) to samples/bulk_fetch.json.
"""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys

MANIFEST = sys.argv[1] if len(sys.argv) > 1 else "tools/sample_urls.json"
SAMPLES = sys.argv[2] if len(sys.argv) > 2 else "samples"
JOBS = int(sys.argv[3]) if len(sys.argv) > 3 else 8
REPORT = os.path.join(SAMPLES, "bulk_fetch.json")

def is_html(path):
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        low = head.lower().lstrip()
        return low.startswith(b"<html") or low.startswith(b"<!doctype") or low.startswith(b"<head")
    except OSError:
        return True

def fetch_one(args):
    task, entry = args
    ext = entry.get("ext") or ""
    # normalise: lower-case extension for the filename
    fname = "task-%03d%s" % (int(task), ext.lower())
    path = os.path.join(SAMPLES, fname)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return (task, {"status": "exists", "file": fname})
    urls = entry.get("urls") or []
    for url in urls:
        tmp = path + ".tmp"
        try:
            r = subprocess.run(
                ["curl", "-sL", "--max-time", "45", "--max-filesize", "52428800",
                 "-A", "Mozilla/5.0 (X11; Linux x86_64) sfile-sample-fetch/1.0",
                 "-o", tmp, url],
                capture_output=True, timeout=60)
        except Exception:
            continue
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            continue
        if is_html(tmp):
            os.remove(tmp)
            continue
        os.rename(tmp, path)
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        return (task, {"status": "ok", "file": fname, "source_url": url,
                       "source": "page", "size": os.path.getsize(path), "sha256": h})
    return (task, {"status": "no-page-url", "note": "all manifest URLs failed or none listed"})

def main():
    m = json.load(open(MANIFEST))
    items = sorted(m.items(), key=lambda kv: int(kv[0]))
    results = {}
    ok = exists = fail = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as ex:
        for task, rec in ex.map(fetch_one, items):
            results[task] = rec
            if rec["status"] == "ok":
                ok += 1
            elif rec["status"] == "exists":
                exists += 1
            else:
                fail += 1
    with open(REPORT, "w") as f:
        json.dump(results, f, indent=1, sort_keys=True)
    print(f"tasks: {len(results)}  downloaded: {ok}  already-existed: {exists}  no-page-url: {fail}")
    print(f"report -> {REPORT}")

if __name__ == "__main__":
    main()
