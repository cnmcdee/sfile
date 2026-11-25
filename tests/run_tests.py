#!/usr/bin/env python3
"""run_tests.py — the sfile test loop.

For every sample in samples/ (see the per-range manifest shards), run
./sfile on it and record whether the format was identified correctly and
whether a header decode was produced.

Pass criteria (automated):
  - IDENTIFIED: sfile's reported task number matches the sample's task,
    or (when the task has a duplicate) the reported extension matches.
  - DECODED: sfile printed a header field table (>=2 fields) or a text
    decode (XML/JSON/text). A bare hex dump does not count as a decode.
A format is PASS only if both hold. IDENTIFIED-but-not-DECODED is PARTIAL
(the format is recognised but has no header layout yet — it needs a hand
override or a sample-derived layout). Anything else is FAIL.

Output:
  tests/results.json — per-format record
  stdout — a summary table + counts

Usage:
    ./tests/run_tests.py [sfile_binary] [samples_dir]
"""
import json
import os
import re
import subprocess
import sys

SFILE = sys.argv[1] if len(sys.argv) > 1 else "./sfile"
SAMPLES = sys.argv[2] if len(sys.argv) > 2 else "samples"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")

def load_manifests():
    merged = {}
    for fname in sorted(os.listdir(SAMPLES)):
        if fname.startswith("manifest-") and fname.endswith(".json"):
            d = json.load(open(os.path.join(SAMPLES, fname)))
            # collectors may key by zero-padded or plain ints; normalize
            for k, v in d.items():
                merged[str(int(k))] = v
    if merged:
        return merged
    # Fallback: no manifest shards yet — derive entries from task-NNN<ext>
    # filenames on disk (used for interim runs while collectors are working).
    # Skip backup/partial files: *.tmp, *.distzip, and double-extension
    # *.gz / *.tar (the real sample is task-NNN.gz / task-NNN.tar).
    for fname in sorted(os.listdir(SAMPLES)):
        if fname.endswith(".tmp") or fname.endswith(".distzip"):
            continue
        # backup files carry a second suffix after the real extension
        # (task-123.foo.gz, task-123.foo.tar, task-123.foo.gz-truncated)
        if re.match(r"task-\d+\.[^.]+\..+$", fname):
            continue
        m = re.match(r"task-(\d+)(\..+)$", fname)
        if m:
            merged[str(int(m.group(1)))] = {"ext": m.group(2), "source": "disk",
                                            "file": fname, "status": "ok"}
    return merged

def junk_reason(path, ext):
    """Why a sample file is junk (a failed download, not a real sample).
    Returns a string, or None if the file looks like a real sample."""
    try:
        sz = os.path.getsize(path)
    except OSError:
        return "missing from disk"
    if sz == 0:
        return "empty file"
    with open(path, "rb") as fh:
        head = fh.read(256)
    if head.startswith(b"404:") or head.startswith(b"404 Not Found"):
        return "404 error page, not a sample"
    if head.startswith(b"<!DOCTYPE html") or head.startswith(b"<html"):
        # An HTML error page saved as a binary sample (real HTML formats
        # are exempt: their samples legitimately start with markup).
        if ext.lower() not in (".html", ".htm", ".xhtml", ".shtml"):
            return "HTML error page, not a sample"
    return None

def main():
    manifests = load_manifests()
    # The full task list is the generated table (849 formats): a task with
    # no sample file on disk is NO SAMPLE, not silently untested.
    fmt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "src", "formats.json")
    all_tasks = set(manifests)
    if os.path.exists(fmt_path):
        all_tasks |= set(json.load(open(fmt_path)))
    results = {}
    n_pass = n_partial = n_fail = n_missing = 0
    for task in sorted(all_tasks, key=lambda x: int(x)):
        m = manifests.get(task)
        if m is None:
            results[task] = {"task": int(task), "result": "no-sample",
                             "note": "no sample file on disk"}
            n_missing += 1
            continue
        rec = {"task": int(task), "ext": m.get("ext"), "source": m.get("source"),
               "sample": m.get("file"), "status": m.get("status")}
        if m.get("status") != "ok" or not m.get("file"):
            rec["result"] = "no-sample"
            n_missing += 1
            results[task] = rec
            continue
        path = os.path.join(SAMPLES, m["file"])
        if not os.path.exists(path):
            rec["result"] = "no-sample"
            rec["note"] = "manifest lists a file that is not on disk"
            n_missing += 1
            results[task] = rec
            continue
        junk = junk_reason(path, m.get("ext") or "")
        if junk:
            rec["result"] = "no-sample"
            rec["note"] = "bad sample: " + junk
            n_missing += 1
            results[task] = rec
            continue
        r = subprocess.run([SFILE, path], capture_output=True, text=True,
                           errors="replace", timeout=30)
        out = r.stdout
        rec["exit"] = r.returncode
        # identified task?
        mm = re.search(r"— task (\d+)", out)
        identified_task = int(mm.group(1)) if mm else None
        rec["identified_task"] = identified_task
        rec["identified"] = (identified_task == int(task))
        # decode produced?
        has_table = bool(re.search(r"offset\s+size\s+field", out))
        has_text = bool(re.search(r"Document type:", out))
        nfields = len(re.findall(r"^\s+\d+\s+\d+\s+\S+", out, re.M))
        rec["decoded"] = bool(has_table and nfields >= 2) or has_text
        rec["nfields"] = nfields if has_table else 0
        rec["how"] = re.search(r"Identified by: (\w+)", out).group(1) if re.search(r"Identified by: (\w+)", out) else None
        if rec["identified"] and rec["decoded"]:
            rec["result"] = "pass"; n_pass += 1
        elif rec["identified"]:
            rec["result"] = "partial"; n_partial += 1
        else:
            rec["result"] = "fail"; n_fail += 1
            rec["output_head"] = out[:400]
        results[task] = rec

    with open(OUT, "w") as f:
        json.dump(results, f, indent=1, sort_keys=True)
    total = len(results)
    print(f"formats tested: {total}")
    print(f"  PASS (identified + decoded): {n_pass}")
    print(f"  PARTIAL (identified, no layout): {n_partial}")
    print(f"  FAIL (misidentified / unknown): {n_fail}")
    print(f"  NO SAMPLE: {n_missing}")
    print(f"results -> {OUT}")
    fails = [t for t, r in results.items() if r["result"] == "fail"]
    if fails:
        print(f"failing tasks: {fails[:40]}{'...' if len(fails) > 40 else ''}")
    partials = [t for t, r in results.items() if r["result"] == "partial"]
    if partials:
        print(f"partial tasks ({len(partials)}): {partials[:40]}{'...' if len(partials) > 40 else ''}")

if __name__ == "__main__":
    main()
