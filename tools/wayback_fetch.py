#!/usr/bin/env python3
"""wayback_fetch.py — Wayback Machine fallback for sfile's missing samples.

DuckDuckGo first (tools/ddg_search.py + tools/ddg_fetch.py). This script
runs AFTER that round, only for formats still without a genuine sample.

Per task, in priority order:
  1. CDX captures of the task page's own download URLs
     (tools/sample_urls.json) — a dead link may have an archived copy.
  2. CDX captures of the DuckDuckGo candidate URLs that failed
     (tools/ddg_candidates.json / tools/ddg_fetch_report.json).
  3. An archived copy of the task page itself (tools/task_page_urls.json)
     — an older capture may list a mirror the live page no longer has.

Captures are fetched raw via the `id_` suffix:
  https://web.archive.org/web/<timestamp>id_/<original-url>
and validated exactly like a DuckDuckGo candidate (magic bytes must match,
./sfile must identify the right task). Genuine samples are saved as
samples/task-NNN<ext> with source "wayback". Report:
tools/wayback_report.json.

Usage:
    python3 tools/wayback_fetch.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ddg_fetch as df  # reuse junk_reason, sfile_identifies, table_magic_matches

SAMPLES = os.path.join(ROOT, "samples")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = df.UA
DELAY = 1.0
# Tasks deliberately not sampled (see ddg_fetch.SKIP_TASKS for reasons).
SKIP_TASKS = {55}


def cdx_captures(url, limit=3):
    """CDX API: up to `limit` captures of `url` (newest first).
    Returns [(timestamp, original_url, mimetype, length), ...]."""
    q = (CDX + "?url=" + urllib.parse.quote(url, safe="") +
         "&output=json&limit=%d&filter=statuscode:200&collapse=digest" % limit)
    try:
        r = subprocess.run(["curl", "-s", "-m", "30", "-A", UA, q],
                           capture_output=True, text=True, timeout=40)
    except Exception:
        return []
    try:
        rows = json.loads(r.stdout)
    except (ValueError, TypeError):
        return []
    if not rows or len(rows) < 2:
        return []
    out = []
    for row in rows[1:]:
        # [urlkey, timestamp, original, mimetype, statuscode, digest, length]
        if len(row) >= 7:
            out.append((row[1], row[2], row[3], row[6]))
    out.sort(key=lambda c: c[0], reverse=True)
    return out


def wayback_url(timestamp, original):
    return "https://web.archive.org/web/%sid_/%s" % (timestamp, original)


def main():
    results = json.load(open(os.path.join(ROOT, "tests", "results.json")))
    formats = json.load(open(os.path.join(ROOT, "src", "formats.json")))
    sample_urls = json.load(open(os.path.join(ROOT, "tools", "sample_urls.json"))) \
        if os.path.exists(os.path.join(ROOT, "tools", "sample_urls.json")) else {}
    task_pages = json.load(open(os.path.join(ROOT, "tools", "task_page_urls.json"))) \
        if os.path.exists(os.path.join(ROOT, "tools", "task_page_urls.json")) else {}
    cand = json.load(open(os.path.join(ROOT, "tools", "ddg_candidates.json"))) \
        if os.path.exists(os.path.join(ROOT, "tools", "ddg_candidates.json")) else {}
    bad = json.load(open(df.BAD)) if os.path.exists(df.BAD) else {}
    report = {}
    if os.path.exists(os.path.join(ROOT, "tools", "wayback_report.json")):
        report = json.load(open(os.path.join(ROOT, "tools", "wayback_report.json")))

    # Targets: tasks with no sample file on disk (still missing after DDG).
    targets = []
    for k, v in sorted(results.items(), key=lambda kv: int(kv[0])):
        if v.get("status") == "not-found" or not v.get("sample"):
            t = int(k)
            if t in SKIP_TASKS:
                continue
            fm = formats.get(k, {})
            ext = (fm.get("ext") or "").lower()
            fname = "task-%03d%s" % (t, ext)
            if not os.path.exists(os.path.join(SAMPLES, fname)):
                targets.append((t, ext))
    # Replacements already in the 107; nothing extra needed.
    print(f"wayback targets: {len(targets)}", flush=True)

    for t, ext in targets:
        key = str(t)
        if report.get(key, {}).get("status", "").startswith("kept"):
            continue
        fname = "task-%03d%s" % (t, ext)
        # Candidate source URLs, in priority order.
        src_urls = []
        seen = set()

        def add(u):
            if u and u not in seen:
                seen.add(u)
                src_urls.append(u)
        for u in (sample_urls.get(key, {}).get("urls") or []):
            add(u)
        for q, r in (cand.get(key, {}).get("queries", {}) or {}).items():
            for res in r.get("results", []):
                add(res.get("url", ""))
        bad_urls = set(bad.get(key, {}).get("urls", []))
        src_urls = [u for u in src_urls if u not in bad_urls]

        kept = None
        tried = []
        # Routes 1+2: archived copies of the source URLs.
        for url in src_urls[:10]:
            caps = cdx_captures(url, limit=3)
            time.sleep(DELAY)
            if not caps:
                tried.append((url, "no wayback captures"))
                continue
            for ts, orig, mime, length in caps:
                wu = wayback_url(ts, orig)
                tmp = os.path.join(SAMPLES, ".wb_tmp_" + fname)
                if not df.fetch(wu, tmp, timeout=60):
                    tried.append((wu, "archived download failed/empty"))
                    continue
                reason = df.junk_reason(tmp, ext)
                if reason:
                    tried.append((wu, reason))
                    os.path.exists(tmp) and os.remove(tmp)
                    continue
                ok, why = df.content_ok(tmp, t, formats, source_url=wu)
                if ok:
                    identified, decoded, _ = df.sfile_identifies(tmp, t, formats)
                    final = os.path.join(SAMPLES, fname)
                    os.rename(tmp, final)
                    kept = {"status": "kept-wayback", "file": fname, "url": wu,
                            "original_url": orig, "capture": ts,
                            "identified_task": identified, "decoded": decoded,
                            "size": os.path.getsize(final), "validation": why}
                    break
                tried.append((wu, why))
                os.path.exists(tmp) and os.remove(tmp)
            if kept:
                break
        # Route 3: archived task page — extract its download links.
        if not kept and task_pages.get(key):
            caps = cdx_captures(task_pages[key], limit=3)
            time.sleep(DELAY)
            for ts, orig, mime, length in caps:
                wu = wayback_url(ts, orig)
                page = os.path.join(SAMPLES, fname + ".wb_page")
                if not df.fetch(wu, page, max_bytes=5 * 1024 * 1024, timeout=30):
                    continue
                with open(page, "rb") as fh:
                    links = df.extract_file_links(fh.read(), task_pages[key], ext)
                os.path.exists(page) and os.remove(page)
                for link in links:
                    tmp = os.path.join(SAMPLES, ".wb_tmp_" + fname)
                    if not df.fetch(link, tmp, timeout=45):
                        continue
                    reason = df.junk_reason(tmp, ext)
                    if reason:
                        os.path.exists(tmp) and os.remove(tmp)
                        continue
                    ok, why = df.content_ok(tmp, t, formats, source_url=link)
                    if ok:
                        identified, decoded, _ = df.sfile_identifies(tmp, t, formats)
                        final = os.path.join(SAMPLES, fname)
                        os.rename(tmp, final)
                        kept = {"status": "kept-wayback-page", "file": fname,
                                "url": link, "task_page_capture": ts,
                                "identified_task": identified, "decoded": decoded,
                                "size": os.path.getsize(final), "validation": why}
                        break
                    os.path.exists(tmp) and os.remove(tmp)
                if kept:
                    break
        if kept:
            report[key] = kept
            print(f"task {t} [{ext}] KEPT via wayback {kept['file']} ({kept['size']} B) {kept['url'][:90]}", flush=True)
        else:
            report[key] = {"status": "not-found", "tried_sources": len(src_urls),
                           "notes": tried[:8]}
            print(f"task {t} [{ext}] still not-found (wayback tried {len(src_urls)} sources)", flush=True)
        with open(os.path.join(ROOT, "tools", "wayback_report.json"), "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)

    kept_n = sum(1 for v in report.values() if v.get("status", "").startswith("kept"))
    print(f"DONE wayback kept={kept_n} report -> tools/wayback_report.json")


if __name__ == "__main__":
    main()
