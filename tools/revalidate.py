#!/usr/bin/env python3
"""Re-validate every sample file for the DDG/Wayback target tasks with the
current strict content_ok, and remove any that fail (false positives kept
by an earlier, weaker validation). Run after all fetching is done."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddg_fetch as df

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")
cand = json.load(open(os.path.join(ROOT, "tools/ddg_candidates.json")))
formats = json.load(open(os.path.join(ROOT, 'src', 'formats.json')))
removed, kept, skipped = [], [], []
for k in sorted((x for x in cand if x != "_special"), key=int):
    t = int(k)
    fm = formats.get(k, {})
    ext = (fm.get("ext") or "").lower()
    if not ext:
        continue
    fname = "task-%03d%s" % (t, ext)
    fpath = os.path.join(SAMPLES, fname)
    if not os.path.exists(fpath):
        continue
    ok, reason = df.content_ok(fpath, t, formats, None)
    if ok:
        kept.append((t, fname, reason))
    else:
        os.remove(fpath)
        removed.append((t, fname, reason))
        print("REMOVED task %d %s: %s" % (t, fname, reason))
print("kept: %s" % kept)
print("removed: %d, kept: %d" % (len(removed), len(kept)))
