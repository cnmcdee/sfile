#!/usr/bin/env python3
"""ddg_search.py — scripted DuckDuckGo (lite endpoint) batch search for
sfile's missing samples and specs.

Queries lite.duckduckgo.com (the html endpoint returns HTTP 202 / no
results from this host; lite returns HTTP 200 with real result links).
Parses the `uddg` param of each `result-link` anchor to recover the
target URL, plus the link title.

Polite: 1.5s between requests, a desktop UA, 30s timeout, one retry.
Resumable: tasks already present in the output file are skipped.

Usage:
    python3 tools/ddg_search.py [out.json]
Default out: tools/ddg_candidates.json
"""
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tools", "ddg_candidates.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
DELAY = 2.0
TIMEOUT = 30
MAX_ATTEMPTS = 3

# Tasks with no format at all (no task page exists) — nothing to search for.
SKIP_TASKS = {202, 214, 292, 389}


def ddg_lite(query):
    """One DuckDuckGo lite search. Returns (http_code, [(title, url), ...]).
    Retries with backoff on non-200 (DDG rate-limits with HTTP 202)."""
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = subprocess.run(
                ["curl", "-s", "-m", str(TIMEOUT), "-A", UA, "-w", "\n%{http_code}", url],
                capture_output=True, text=True, timeout=TIMEOUT + 10)
        except Exception as e:  # noqa: BLE001
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(DELAY * (attempt + 2))
                continue
            return 0, []
        out = r.stdout
        code = out.rsplit("\n", 1)[-1].strip()
        body = out[:out.rfind("\n")] if "\n" in out else out
        try:
            http = int(code)
        except ValueError:
            http = 0
        if http != 200:
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(DELAY * (attempt + 2))
                continue
            return http, []
        results = []
        # <a rel="nofollow" href="//duckduckgo.com/l/?uddg=<urlenc>&rut=..." class='result-link'>TITLE</a>
        for m in re.finditer(
                r"<a[^>]*href=\"//duckduckgo\.com/l/\?uddg=([^&\"']+)[^>]*class='result-link'>(.*?)</a>",
                body, re.S):
            target = urllib.parse.unquote(m.group(1))
            title = re.sub(r"<[^>]+>", "", html.unescape(m.group(2))).strip()
            if target.startswith("http"):
                results.append({"title": title, "url": target})
        return http, results
    return 0, []


def clean_name(name):
    """Turn a formats.json name into a usable search phrase."""
    n = (name or "").strip()
    n = re.sub(r"\s+file$", "", n, flags=re.I)
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def main():
    results = json.load(open(os.path.join(ROOT, "tests", "results.json")))
    formats = json.load(open(os.path.join(ROOT, "src", "formats.json")))
    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT))

    targets = []
    for k, v in sorted(results.items(), key=lambda kv: int(kv[0])):
        if v.get("status") != "not-found" and v.get("sample"):
            continue
        t = int(k)
        if t in SKIP_TASKS:
            continue
        fm = formats.get(k, {})
        targets.append((t, (fm.get("ext") or "").lower(), clean_name(fm.get("name", ""))))
    # Replacement samples for dropped ones (005 and 024 are not in the
    # no-sample list; 373 already is, but gets its own extra queries).
    targets.append((5, ".3gx", "3GPP2 video"))
    targets.append((24, ".amf", "Action Message Format AMF"))

    total_q = 0
    for t, ext, name in targets:
        key = str(t)
        # Resume: keep queries that already returned HTTP 200 with
        # results; re-run the ones that were rate-limited (202) or empty.
        existing = out.get(key, {})
        done = {}
        if existing.get("queries"):
            for q, r in existing["queries"].items():
                if r.get("http") == 200 and r.get("results"):
                    done[q] = r
        queries = []
        if ext:
            queries.append(f"sample {ext} file download")
        if name:
            queries.append(f"{name} sample file example download")
        entry = {"ext": ext, "name": name, "queries": dict(done)}
        for q in queries:
            if q in done:
                continue
            http, res = ddg_lite(q)
            entry["queries"][q] = {"http": http, "results": res}
            total_q += 1
            print(f"task {t} [{ext}] q={q!r} http={http} n={len(res)}", flush=True)
            time.sleep(DELAY)
        out[key] = entry
        with open(OUT, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)

    # Spec research (not sample-hunting): EXS24 layout + replacement specifics.
    specials = {
        "exs_spec": [
            "EXS24 file format specification",
            "EXS24 sampler file format parser",
            "Logic EXS24 .exs file structure header",
            "EXS24 instrument file format reverse engineering",
        ],
        "005_3g2": [
            "3GPP2 .3g2 sample video file download",
            "sample .3g2 file download",
        ],
        "024_amf": [
            "AMF Action Message Format sample .amf file download",
            "sample .amf binary file download",
        ],
        "373_m4v": [
            "sample .m4v file download small",
            "free sample .m4v video file download",
        ],
    }
    sp = out.get("_special", {})
    for section, queries in specials.items():
        existing = sp.get(section, {})
        done = {}
        if existing.get("queries"):
            for q, r in existing["queries"].items():
                if r.get("http") == 200 and r.get("results"):
                    done[q] = r
        entry = {"queries": dict(done)}
        for q in queries:
            if q in done:
                continue
            http, res = ddg_lite(q)
            entry["queries"][q] = {"http": http, "results": res}
            total_q += 1
            print(f"special {section} q={q!r} http={http} n={len(res)}", flush=True)
            time.sleep(DELAY)
        sp[section] = entry
        out["_special"] = sp
        with open(OUT, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)

    print(f"DONE queries={total_q} tasks={len(out) - (1 if '_special' in out else 0)}")
    print(f"candidates -> {OUT}")


if __name__ == "__main__":
    main()
