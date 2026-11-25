#!/usr/bin/env python3
"""ddg_fetch.py — download and validate DuckDuckGo candidate sample files.

Reads tools/ddg_candidates.json, tries each candidate URL, and keeps the
first genuine sample per task.

A candidate URL is either a direct file link or a page. For a page, all
hrefs ending in the target extension (or containing it + "download")
are tried as direct file links.

A download is genuine only if:
  - non-empty, <= 50 MiB, and not an HTML/JS/PDF error page (magic check);
  - ./sfile identifies it as the target task (identified_task == task),
    OR its magic matches the table magic for that task (extension-only
    formats whose sample sfile cannot confirm by magic alone).

Genuine samples are saved as samples/task-NNN<ext> (lowercase ext) so
tests/run_tests.py picks them up. Bad URLs are appended to
tools/bad_page_urls.json. A report goes to tools/ddg_fetch_report.json.

Usage:
    python3 tools/ddg_fetch.py [candidates.json]
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tools", "ddg_candidates.json")
SAMPLES = os.path.join(ROOT, "samples")
SFILE = os.path.join(ROOT, "sfile")
BAD = os.path.join(ROOT, "tools", "bad_page_urls.json")
REPORT = os.path.join(ROOT, "tools", "ddg_fetch_report.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
MAX_BYTES = 50 * 1024 * 1024

# Domains that never host a downloadable sample (search engines, docs, video).
SKIP_DOMAINS = {
    "duckduckgo.com", "www.duckduckgo.com", "google.com", "www.google.com",
    "bing.com", "www.bing.com", "wikipedia.org", "en.wikipedia.org",
    "youtube.com", "www.youtube.com",
    "stackoverflow.com", "www.stackoverflow.com", "reddit.com", "www.reddit.com",
    "quora.com", "www.quora.com", "amazon.com", "www.amazon.com",
}
# NOTE: github.com is deliberately NOT skipped — blob URLs are rewritten
# to raw.githubusercontent.com (see github_raw) and downloaded directly.

# Real-world extension aliases: the file on disk often uses a sibling
# extension to the table ext (e.g. 3GPP2 files are .3g2, not .3gx).
ALIASES = {
    5: [".3g2", ".3gp"],
    373: [".mp4"],
}

# URL path suffixes that are pages, not files.
PAGE_SUFFIXES = (".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".cgi", "/")


def github_raw(url):
    """github.com/<owner>/<repo>/blob/<branch>/<path> ->
    raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>.
    Returns the raw URL, or None if not a blob URL."""
    m = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", url)
    if not m:
        return None
    owner, repo, branch, path = m.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


def is_direct_file_url(url):
    """True if the URL looks like a direct file (not a web page)."""
    if url.startswith("https://raw.githubusercontent.com/"):
        return True
    path = urllib.parse.urlparse(url).path.lower()
    if not path or path.endswith(PAGE_SUFFIXES):
        return False
    # A path with a file-like extension (not a page) is a direct file.
    return bool(re.search(r"\.[a-z0-9]{1,5}$", path))


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception:
        return 1, b"", b""


def fetch(url, path, max_bytes=MAX_BYTES, timeout=45):
    """curl a URL to a file. Returns True if a non-empty file was written."""
    rc, _, _ = run(["curl", "-sL", "--max-time", str(timeout),
                    "--max-filesize", str(max_bytes), "-A", UA, "-o", path, url],
                   timeout=timeout + 15)
    return os.path.exists(path) and os.path.getsize(path) > 0


def junk_reason(path, ext):
    """Same junk rules as tests/run_tests.py, plus JS and PDF."""
    try:
        sz = os.path.getsize(path)
    except OSError:
        return "missing"
    if sz == 0:
        return "empty file"
    with open(path, "rb") as fh:
        head = fh.read(256)
    low = head.lstrip().lower()
    if head.startswith(b"404:") or head.startswith(b"404 Not Found"):
        return "404 error page"
    if low.startswith(b"<!doctype") or low.startswith(b"<html") or low.startswith(b"<head"):
        if ext.lower() not in (".html", ".htm", ".xhtml", ".shtml"):
            return "HTML error page"
    if low.startswith(b"%pdf"):
        if ext.lower() != ".pdf":
            return "PDF document, not a sample"
    if low.startswith(b"//") or b"function(" in head[:256] and ext.lower() == ".js":
        return "JavaScript, not a sample"
    if head[:2] == b"PK" and ext.lower() not in (".zip",):
        # A ZIP where the format is not ZIP-based is suspicious, but ZIP
        # containers are legitimate for many formats — let sfile decide.
        pass
    return None


def sfile_identifies(path, task, formats):
    """Run ./sfile on the file. Returns (identified_task, decoded, output)."""
    rc, out, _ = run([SFILE, path], timeout=30)
    text = out.decode(errors="replace")
    m = re.search(r"— task (\d+)", text)
    identified = int(m.group(1)) if m else None
    has_table = bool(re.search(r"offset\s+size\s+field", text))
    nfields = len(re.findall(r"^\s+\d+\s+\d+\s+\S+", text, re.M))
    decoded = bool(has_table and nfields >= 1) or bool(re.search(r"Document type:", text))
    return identified, decoded, text


def table_magic_matches(path, task, formats):
    """Does the file's leading bytes match the table magic for the task?"""
    fm = formats.get(str(task), {})
    magic = fm.get("magic")
    off = fm.get("magic_off", 0) or 0
    if not magic:
        return False
    try:
        raw = bytes.fromhex(magic)
    except ValueError:
        return False
    try:
        with open(path, "rb") as fh:
            fh.seek(off)
            head = fh.read(len(raw))
    except OSError:
        return False
    return head == raw


def extract_file_links(page_bytes, base_url, ext, task=None):
    """All hrefs in an HTML page that look like a direct file of this ext.
    Accepts the table ext, its real-world aliases, and any href with
    'download' in it that ends in a file-like (non-page) extension."""
    text = page_bytes.decode(errors="replace")
    ext_l = ext.lower()
    accept = {ext_l}
    for a in (ALIASES.get(task) or []):
        accept.add(a.lower())
    links = []
    for m in re.finditer(r'''href\s*=\s*["']([^"']+)["']''', text, re.I):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urllib.parse.urljoin(base_url, href)
        path = urllib.parse.urlparse(full).path.lower()
        if any(path.endswith(a) for a in accept):
            links.append(full)
        elif "download" in full.lower() and is_direct_file_url(full):
            links.append(full)
    # Dedupe, preserve order.
    seen, out = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:8]


def main():
    cand = json.load(open(CAND))
    formats = json.load(open(os.path.join(ROOT, "src", "formats.json")))
    results = json.load(open(os.path.join(ROOT, "tests", "results.json")))
    bad = json.load(open(BAD)) if os.path.exists(BAD) else {}
    report = {}
    if os.path.exists(REPORT):
        report = json.load(open(REPORT))

    tasks = sorted((int(k) for k in cand if k != "_special"))
    for t in tasks:
        key = str(t)
        entry = cand[key]
        ext = entry.get("ext", "")
        if not ext:
            fm = formats.get(key, {})
            ext = (fm.get("ext") or "").lower()
        # Already have a genuine sample on disk? (e.g. from a previous run)
        fname = "task-%03d%s" % (t, ext.lower())
        if os.path.exists(os.path.join(SAMPLES, fname)) and os.path.getsize(os.path.join(SAMPLES, fname)) > 0:
            report[key] = {"status": "exists", "file": fname}
            continue
        if report.get(key, {}).get("status") == "kept":
            continue
        # Candidate URLs, deduped, in query order.
        urls = []
        seen = set()
        for q, r in entry.get("queries", {}).items():
            for res in r.get("results", []):
                u = res.get("url", "")
                if u and u not in seen:
                    seen.add(u)
                    urls.append(u)
        # Drop known-bad domains and URLs already recorded bad for this task.
        bad_urls = set(bad.get(key, {}).get("urls", []))
        urls = [u for u in urls if u not in bad_urls
                and urllib.parse.urlparse(u).netloc.lower() not in SKIP_DOMAINS]
        kept = None
        tried_bad = []
        for url in urls[:12]:
            # Temp file keeps the TARGET extension (leading dot hides it
            # from the test runner) so sfile's extension disambiguation
            # sees the right ext when validating the candidate.
            tmp = os.path.join(SAMPLES, ".ddg_tmp_" + fname)
            # GitHub blob page -> raw file URL (direct download).
            raw = github_raw(url)
            if raw:
                url = raw
            # Direct file link? (any file-like URL, not just the table ext —
            # content validation decides whether it is the right format.)
            direct = is_direct_file_url(url)
            if direct:
                if not fetch(url, tmp):
                    tried_bad.append((url, "download failed/empty"))
                    continue
            else:
                # Page: fetch and extract direct file links.
                page = os.path.join(SAMPLES, fname + ".ddg_page")
                if not fetch(url, page, max_bytes=5 * 1024 * 1024, timeout=30):
                    tried_bad.append((url, "page fetch failed"))
                    continue
                with open(page, "rb") as fh:
                    links = extract_file_links(fh.read(), url, ext, task=t)
                os.path.exists(page) and os.remove(page)
                if not links:
                    tried_bad.append((url, "no direct file link on page"))
                    continue
                got = False
                for link in links:
                    link_raw = github_raw(link) or link
                    if fetch(link_raw, tmp):
                        got = True
                        url = link_raw
                        break
                if not got:
                    tried_bad.append((url, "direct links failed to download"))
                    continue
            # Validate the downloaded file.
            reason = junk_reason(tmp, ext)
            if reason:
                tried_bad.append((url, reason))
                os.path.exists(tmp) and os.remove(tmp)
                continue
            identified, decoded, _ = sfile_identifies(tmp, t, formats)
            if identified == t:
                final = os.path.join(SAMPLES, fname)
                os.rename(tmp, final)
                kept = {"status": "kept", "file": fname, "url": url,
                        "identified_task": identified, "decoded": decoded,
                        "size": os.path.getsize(final)}
                break
            if table_magic_matches(tmp, t, formats):
                # Genuine magic, but sfile did not identify it (extension
                # or table gap). Keep it — the test run will show PARTIAL
                # or FAIL honestly, and the sample is real.
                final = os.path.join(SAMPLES, fname)
                os.rename(tmp, final)
                kept = {"status": "kept-magic-only", "file": fname, "url": url,
                        "identified_task": identified, "decoded": decoded,
                        "size": os.path.getsize(final)}
                break
            tried_bad.append((url, f"sfile identified task {identified}, not {t}"))
            os.path.exists(tmp) and os.remove(tmp)
        if kept:
            report[key] = kept
            print(f"task {t} [{ext}] KEPT {kept['file']} ({kept['size']} B) via {kept['url'][:80]}", flush=True)
        else:
            report[key] = {"status": "not-found", "tried": len(urls),
                           "bad": tried_bad[:12]}
            # Record the bad URLs so they are not re-fetched.
            if tried_bad:
                rec = bad.get(key, {"ext": ext.upper(), "reason": "DDG candidates rejected", "urls": []})
                have = set(rec.get("urls", []))
                for u, _ in tried_bad:
                    if u not in have:
                        rec.setdefault("urls", []).append(u)
                        have.add(u)
                bad[key] = rec
            print(f"task {t} [{ext}] not-found (tried {len(urls)} candidates)", flush=True)
        with open(REPORT, "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)
        with open(BAD, "w") as f:
            json.dump(bad, f, indent=1, sort_keys=True)

    kept_n = sum(1 for v in report.values() if v.get("status", "").startswith("kept"))
    print(f"DONE kept={kept_n} report -> {REPORT}")


if __name__ == "__main__":
    main()
