#!/usr/bin/env python3
"""apply_testloop_overrides6.py — sixth batch (Nov 25, 2026 test loop).
242 FREQ (SAM freq files are text; the PLINK .frq sample is a different
format), 300 ICE (LHA variant; sample was a byte-identical copy of the
355 LHA archive), 762 V64 (extracted the real ROM from its LHA archive).
Run: python3 tools/apply_testloop_overrides6.py  (then: make table)
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ov = json.load(open(os.path.join(HERE, "overrides.json")))

# 242: SAM .freq files are text (the code reads lines with fgets and looks
# for the ENDFREQUENCIES marker). The magic was a section marker, not a
# file signature. The sample was a PLINK .frq (a different format).
ov["242"] = {"magic": None, "derivation": "text",
             "notes": "SAM frequency files are text (fgets line parser); ENDFREQUENCIES is a section marker, not a signature"}

# 300 ICE: an LHA/LZH variant (Amiga/ICEOWS). Same header as LHA.
LHA_FIELDS = [
    {"name": "header_len", "offset": 0, "size": 1, "kind": "u8"},
    {"name": "checksum", "offset": 1, "size": 1, "kind": "u8"},
    {"name": "method", "offset": 2, "size": 5, "kind": "ascii"},
    {"name": "comp_size", "offset": 7, "size": 4, "kind": "u32"},
    {"name": "uncomp_size", "offset": 11, "size": 4, "kind": "u32"},
    {"name": "timestamp_raw", "offset": 15, "size": 4, "kind": "u32"},
    {"name": "attr", "offset": 19, "size": 1, "kind": "u8"},
    {"name": "level", "offset": 20, "size": 1, "kind": "u8"}]
ov["300"] = {"ext": ".ICE", "name": "ICE file", "magic": "2d6c68",
             "magic_off": 2, "fields": LHA_FIELDS, "derivation": "override",
             "notes": "ICE is an LHA/LZH variant (same header); the sample is an LHA-structured archive"}
ov["355"]["name"] = "LHA file"

with open(os.path.join(HERE, "overrides.json"), "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)

SAMPLES = os.path.join(ROOT, "samples")
BACKUPS = os.path.join(SAMPLES, ".backups")
os.makedirs(BACKUPS, exist_ok=True)

# 242: delete the wrong PLINK sample.
for f in os.listdir(SAMPLES):
    if f.startswith("task-242."):
        os.remove(os.path.join(SAMPLES, f))
        print("deleted wrong sample:", f)

# 300: the sample is an LHA-structured archive; rename to .ice.
for f in list(os.listdir(SAMPLES)):
    if f.startswith("task-300."):
        os.rename(os.path.join(SAMPLES, f), os.path.join(SAMPLES, "task-300.ice"))
        print("renamed:", f, "-> task-300.ice")

# 762: replace the LHA distribution archive with the extracted V64 file.
for f in list(os.listdir(SAMPLES)):
    if f.startswith("task-762."):
        shutil.move(os.path.join(SAMPLES, f), os.path.join(BACKUPS, f + ".distlha"))
        print("archived distribution LHA:", f)
shutil.copy("/tmp/v64x/V64_VER1.30", os.path.join(SAMPLES, "task-762.v64"))
print("installed extracted V64 file as task-762.v64 (262144 bytes)")
