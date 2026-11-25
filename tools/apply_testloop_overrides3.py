#!/usr/bin/env python3
"""apply_testloop_overrides3.py — third batch of hand overrides from the
Nov 25, 2026 test loop (round 3: 15 FAILs). Every entry was verified
against a real sample file, the task page, or the reference code block.
Run: python3 tools/apply_testloop_overrides3.py  (then: make table)
"""
import json
import os

OV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")
ov = json.load(open(OV))

NEW = {
    # ZRX is a line-oriented TEXT format (Kisters ZRXP time series); the
    # ## 'magic' matched any text file starting with ## (AWK, Markdown,
    # PEM, .properties, R source). Removing it fixes 5 tasks at once.
    "858": {"magic": None, "derivation": "text",
            "notes": "ZRX/ZRXP is line-oriented text; the ## magic matched any ## text file"},
    # ICS is iCalendar under the .ics extension (same format as .ical).
    "304": {"magic": "424547494e3a5643414c454e444152", "derivation": "text",
            "notes": "ICS is iCalendar (same format as ICAL, task 298)"},
    # OGX: the code's 'fishead' magic is the Ogg Skeleton track header,
    # not the OGX container; real OGX files start with OggS.
    "481": {"magic": "4f676753",
            "notes": "OGX is an Ogg container (OggS); the fishead magic is a skeleton-track header, not the file magic"},
    # MKA: the page is about Matroska Audio; the recorded .files ext is junk.
    "398": {"ext": ".MKA", "magic": "1a45dfa3",
            "notes": "page is about .MKA (Matroska Audio, EBML); the .files extension was a bad extraction"},
    # SEC and VVVVVV are XML files that lacked the <?xml magic.
    "652": {"magic": "3c3f786d6c", "derivation": "text",
            "notes": "SEC is XML (<?xml ...><SEC ...); the sample is the extracted inner file"},
    "801": {"magic": "3c3f786d6c", "derivation": "text",
            "notes": "VVVVVV level files are XML (<MapData ...)"},
    # REXX: ooRexx scripts carry this shebang; the /* magic was removed
    # earlier as over-broad (it matched any C-style comment).
    "612": {"magic": "2321404f4f524558585f53484542414e475f50524f4752414d40",
            "derivation": "text",
            "notes": "ooRexx script; #!@OOREXX_SHEBANG_PROGRAM@ shebang"},
}

for k, v in NEW.items():
    ov[k] = v
# Fix a hex typo in batch 2: QT's brand is "qt  " (71 74 20 20), not "ht  ".
ov["591"]["magic"] = "6674797071742020"
ov["591"]["notes"] = "QuickTime ftyp box, major brand qt  (batch-2 hex typo fixed: ht -> qt)"
with open(OV, "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)
print(f"overrides: {len(ov)} total, {len(NEW)} added/updated + 591 hex fix")
