#!/usr/bin/env python3
"""apply_testloop_overrides9.py — ninth batch (Nov 25, 2026 test loop).
Fixes the 8 FAILs from the batch-8 run: .A is an ar archive too, the
3DS 'MM' magic stole a big-endian GeoTIFF, .NCD is NetCDF, .WL is a
DICOM worklist, .FFAPX is a ZIP, and three wrong samples deleted.
Run: python3 tools/apply_testloop_overrides9.py  (then: make table)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ov = json.load(open(os.path.join(HERE, "overrides.json")))

# .A static libraries are ar archives (same as .deb).
ov["9"] = {"magic": "213c617263683e0a",
           "notes": "static libraries are ar archives, like .deb"}
# GeoTIFF (big-endian TIFF). The 3DS 'MM' magic stole it because this
# format had no TIFF magic of its own.
ov["257"] = {"magic": "4d4d002a",
             "notes": "big-endian TIFF; inherits the TIFF-BE layout"}
# NCD is NetCDF classic (same as .NC).
ov["442"] = {"magic": "434446", "endian": "be",
             "fields": [{"name": "magic", "offset": 0, "size": 3, "kind": "ascii"},
                        {"name": "version", "offset": 3, "size": 1, "kind": "u8"},
                        {"name": "numrecs", "offset": 4, "size": 4, "kind": "u32"}],
             "derivation": "override",
             "notes": "NetCDF classic (same layout as .NC, task 441)"}
# WL is a DICOM worklist (a DICOM file; DICM at 128).
ov["811"] = {"magic": "4449434d", "magic_off": 128,
             "fields": [{"name": "preamble", "offset": 0, "size": 128, "kind": "bytes"},
                        {"name": "dicom_magic", "offset": 128, "size": 4, "kind": "ascii"}],
             "derivation": "override",
             "notes": "DICOM worklist (a DICOM file; DICM at 128)"}
# E00 (ESRI ArcInfo interchange) is ASCII text; the sample was an S3 error page.
ov["163"] = {"fields": [], "derivation": "text",
             "notes": "E00 ArcInfo interchange files are ASCII text"}
# Factor source files are text; the sample was a PDF manual.
ov["213"] = {"fields": [], "derivation": "text",
             "notes": "Factor source files are text"}
with open(os.path.join(HERE, "overrides.json"), "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)

# ar container layout + FFAPX as a ZIP.
p = os.path.join(HERE, "gen_formats.py")
s = open(p).read()
ar = '''    ("213c617263683e0a", 0): [  # ar archive header + first member header
        {"name": "signature", "offset": 0, "size": 8, "kind": "ascii"},
        {"name": "first_member_name", "offset": 8, "size": 16, "kind": "ascii"},
        {"name": "first_member_mtime", "offset": 24, "size": 12, "kind": "ascii"},
        {"name": "first_member_uid", "offset": 36, "size": 6, "kind": "ascii"},
        {"name": "first_member_gid", "offset": 42, "size": 6, "kind": "ascii"},
        {"name": "first_member_mode", "offset": 48, "size": 8, "kind": "ascii"},
        {"name": "first_member_size", "offset": 56, "size": 10, "kind": "ascii"},
        {"name": "first_member_magic", "offset": 66, "size": 2, "kind": "ascii"},
    ],
'''
anchor = '    ("464f524d", 0): [  # IFF FORM header (same shape as RIFF)'
assert anchor in s
s = s.replace(anchor, ar + anchor)
s = s.replace('".MSCZ": "504b0304", ".OTS": "504b0304", ".PPSX": "504b0304", ".KRA": "504b0304", ".PK3": "504b0304",',
              '".MSCZ": "504b0304", ".OTS": "504b0304", ".PPSX": "504b0304", ".KRA": "504b0304", ".PK3": "504b0304", ".FFAPX": "504b0304",')
open(p, "w").write(s)

# Delete the three wrong samples.
SAMPLES = os.path.join(ROOT, "samples")
for t in ["69", "163", "213"]:
    for f in list(os.listdir(SAMPLES)):
        if f.startswith(f"task-{int(t):03d}."):
            os.remove(os.path.join(SAMPLES, f))
            print("deleted wrong sample:", f)
print("batch 9 applied")
