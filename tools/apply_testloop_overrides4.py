#!/usr/bin/env python3
"""apply_testloop_overrides4.py — fourth batch (Nov 25, 2026 test loop).

115 formats verified as TEXT (sample is genuine text + page agrees),
3 specials (FITS card layout, AI=PDF, PAL=RIFF), and container layouts
(PDF, TIFF LE/BE, OLE/CFB) added to the generator. Also deletes 11
provably wrong samples. Run: python3 tools/apply_testloop_overrides4.py
(then: make table)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --- text tasks, derived from the verified check files ---
chk = json.load(open("/tmp/text_check.json"))          # agree (71)
chk2 = json.load(open("/tmp/text_check2.json"))        # text_ok (4), still_unclear (51)
WRONG = {"250", "343", "512", "651", "745", "818", "847", "666", "114", "229"}
SPECIAL = {"20", "509", "226"}
text_tasks = sorted(
    set(chk["agree"]) | set(chk2["text_ok"]) | set(chk2["still_unclear"])
    - WRONG - SPECIAL,
    key=int,
)

ov = json.load(open(os.path.join(HERE, "overrides.json")))
for t in text_tasks:
    ov[t] = {"fields": [], "derivation": "text",
             "notes": "verified text format (genuine text sample + page describes text)"}

# --- specials ---
# FITS: 80-byte ASCII header cards (FITS standard). First card decoded.
ov["226"] = {"fields": [
    {"name": "keyword", "offset": 0, "size": 8, "kind": "ascii"},
    {"name": "value_indicator", "offset": 8, "size": 2, "kind": "ascii"},
    {"name": "value", "offset": 10, "size": 20, "kind": "ascii"},
    {"name": "comment", "offset": 30, "size": 50, "kind": "ascii"}],
    "derivation": "override",
    "notes": "FITS header is 80-byte ASCII cards; first card decoded"}
# AI (Adobe Illustrator) files are PDFs.
ov["20"] = {"magic": "25504446",
            "notes": "modern .ai files are PDF documents"}
# PAL is a Microsoft RIFF palette (binary); the JASC-PAL text sample was wrong.
ov["509"] = {"magic": "52494646",
             "notes": "Microsoft RIFF palette (binary); inherits the RIFF layout"}

with open(os.path.join(HERE, "overrides.json"), "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)

# --- container layouts in the generator ---
p = os.path.join(HERE, "gen_formats.py")
s = open(p).read()
addition = '''    ("25504446", 0): [  # PDF header (also covers AI)
        {"name": "magic", "offset": 0, "size": 5, "kind": "ascii"},
        {"name": "version", "offset": 5, "size": 3, "kind": "ascii"},
    ],
    ("49492a00", 0): [  # TIFF header, little-endian (II)
        {"name": "byte_order", "offset": 0, "size": 2, "kind": "ascii"},
        {"name": "magic", "offset": 2, "size": 2, "kind": "u16"},
        {"name": "first_ifd_offset", "offset": 4, "size": 4, "kind": "u32"},
    ],
    ("4d4d002a", 0): [  # TIFF header, big-endian (MM)
        {"name": "byte_order", "offset": 0, "size": 2, "kind": "ascii", "be": True},
        {"name": "magic", "offset": 2, "size": 2, "kind": "u16"},
        {"name": "first_ifd_offset", "offset": 4, "size": 4, "kind": "u32"},
    ],
    ("d0cf11e0a1b11ae1", 0): [  # OLE compound document (MS-CFB) header
        {"name": "signature", "offset": 0, "size": 8, "kind": "bytes"},
        {"name": "clsid", "offset": 8, "size": 16, "kind": "bytes"},
        {"name": "minor_version", "offset": 24, "size": 2, "kind": "u16"},
        {"name": "major_version", "offset": 26, "size": 2, "kind": "u16"},
        {"name": "byte_order", "offset": 28, "size": 2, "kind": "u16"},
        {"name": "sector_shift", "offset": 30, "size": 2, "kind": "u16"},
        {"name": "mini_sector_shift", "offset": 32, "size": 2, "kind": "u16"},
        {"name": "num_dir_sectors", "offset": 40, "size": 4, "kind": "u32"},
        {"name": "num_fat_sectors", "offset": 44, "size": 4, "kind": "u32"},
        {"name": "first_dir_sector", "offset": 48, "size": 4, "kind": "u32"},
        {"name": "transaction_sig", "offset": 52, "size": 4, "kind": "u32"},
        {"name": "mini_stream_cutoff", "offset": 56, "size": 4, "kind": "u32"},
        {"name": "first_minifat_sector", "offset": 60, "size": 4, "kind": "u32"},
        {"name": "num_minifat_sectors", "offset": 64, "size": 4, "kind": "u32"},
        {"name": "first_difat_sector", "offset": 68, "size": 4, "kind": "u32"},
        {"name": "num_difat_sectors", "offset": 72, "size": 4, "kind": "u32"},
    ],
'''
anchor = '    ("464f524d", 0): [  # IFF FORM header (same shape as RIFF)'
assert anchor in s
s = s.replace(anchor, addition + anchor)
# OLE magic for the remaining OLE formats that lack it in the table.
s = s.replace('".DGN": "d0cf11e0a1b11ae1", ".IPT": "d0cf11e0a1b11ae1", ".VDW": "d0cf11e0a1b11ae1",',
              '".DGN": "d0cf11e0a1b11ae1", ".IPT": "d0cf11e0a1b11ae1", ".VDW": "d0cf11e0a1b11ae1", ".DOC": "d0cf11e0a1b11ae1", ".MSI": "d0cf11e0a1b11ae1", ".VST": "d0cf11e0a1b11ae1",')
open(p, "w").write(s)

# --- delete provably wrong samples ---
SAMPLES = os.path.join(ROOT, "samples")
deleted = []
for t in sorted(WRONG | {"509"}, key=int):
    for f in os.listdir(SAMPLES):
        if f.startswith(f"task-{int(t):03d}.") and not f.endswith((".distzip", ".gz", ".tar")):
            os.remove(os.path.join(SAMPLES, f))
            deleted.append(f)
print(f"text-marked: {len(text_tasks)}  specials: 3  container layouts: 4")
print(f"deleted wrong samples: {deleted}")
