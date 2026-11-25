#!/usr/bin/env python3
"""apply_testloop_overrides5.py — fifth batch (Nov 25, 2026 test loop).
FODG's bogus 'xmlns:' magic, LHA (ext .LGA was wrong; the code's crc/count
fields are wrong — filename is variable-length), PK3=ZIP.
Run: python3 tools/apply_testloop_overrides5.py  (then: make table)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ov = json.load(open(os.path.join(HERE, "overrides.json")))

# FODG is flat ODF (XML); the code-derived 'xmlns:' magic is a namespace
# prefix, not a file signature.
ov["235"] = {"magic": "3c3f786d6c", "derivation": "text",
             "notes": "FODG is flat ODF (XML); the xmlns: magic is a namespace prefix, not a signature"}

# LHA: the page and the code are about LHA (also .LZH); .LGA is a bad
# extraction. Method string '-lh5-' etc. at offset 2. The struct-derived
# crc/count fields are wrong: filename is variable-length, so crc follows
# it; count belongs to the handler struct, not the entry.
ov["355"] = {
    "ext": ".LHA", "magic": "2d6c68", "magic_off": 2,
    "fields": [
        {"name": "header_len", "offset": 0, "size": 1, "kind": "u8"},
        {"name": "checksum", "offset": 1, "size": 1, "kind": "u8"},
        {"name": "method", "offset": 2, "size": 6, "kind": "ascii"},
        {"name": "comp_size", "offset": 8, "size": 4, "kind": "u32"},
        {"name": "uncomp_size", "offset": 12, "size": 4, "kind": "u32"},
        {"name": "timestamp_raw", "offset": 16, "size": 4, "kind": "u32"},
        {"name": "attr", "offset": 20, "size": 1, "kind": "u8"},
        {"name": "level", "offset": 21, "size": 1, "kind": "u8"}],
    "derivation": "override",
    "notes": "LHA archive; .LGA was a bad extraction; crc follows the variable-length filename so it has no fixed offset"}

with open(os.path.join(HERE, "overrides.json"), "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)

p = os.path.join(HERE, "gen_formats.py")
s = open(p).read()
s = s.replace('".MSCZ": "504b0304", ".OTS": "504b0304", ".PPSX": "504b0304", ".KRA": "504b0304",',
              '".MSCZ": "504b0304", ".OTS": "504b0304", ".PPSX": "504b0304", ".KRA": "504b0304", ".PK3": "504b0304",')
open(p, "w").write(s)
print("overrides: 235, 355; table: .PK3 -> ZIP")
