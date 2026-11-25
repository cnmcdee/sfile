#!/usr/bin/env python3
"""apply_testloop_overrides2.py — second batch of hand overrides from the
Nov 25, 2026 test loop (round 2: 48 FAILs). Every entry was verified
against a real sample file, the task page, or the reference code block.
Run: python3 tools/apply_testloop_overrides2.py  (then: make table)
"""
import json
import os

OV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")
ov = json.load(open(OV))

JFIF_FIELDS = [{"name": "soi", "offset": 0, "size": 2, "kind": "bytes"},
               {"name": "marker", "offset": 2, "size": 2, "kind": "bytes"},
               {"name": "segment_length", "offset": 4, "size": 2, "kind": "u16"},
               {"name": "identifier", "offset": 6, "size": 5, "kind": "ascii"}]

NEW = {
    # IFF FORM: AIFF's form type is AIFF at offset 8; FORM@0 alone
    # collides with LWO (task 364). Both magics are 4 bytes; the table
    # order (22 < 364) and the extension disambiguation settle AIFF files.
    "22": {"magic": "41494646", "magic_off": 8,
           "notes": "AIFF is IFF FORM with form type AIFF at offset 8"},
    # ISO BMFF ftyp + major brand (8-byte magic beats MP4's bare ftyp;
    # the engine's extension disambiguation settles plain .mp4 files
    # whose brand is isom/mp42).
    "48": {"magic": "6674797061766966", "magic_off": 4,
           "notes": "AVIF ftyp box, major brand avif"},
    "207": {"magic": "6674797066347620", "magic_off": 4,
            "notes": "F4V ftyp box, major brand f4v "},
    "286": {"magic": "6674797068656963", "magic_off": 4,
            "notes": "HEIC ftyp box, major brand heic; HEIF (287) shares the brand"},
    "287": {"magic": "6674797068656963", "magic_off": 4,
            "notes": "HEIF ftyp box, major brand heic; HEIC (286) shares the brand"},
    "372": {"magic": "6674797069736f6d", "magic_off": 4,
            "notes": "M4R ftyp box, major brand isom"},
    "373": {"magic": "667479704d345620", "magic_off": 4,
            "notes": "M4V ftyp box, major brand M4V "},
    "591": {"magic": "6674797068742020", "magic_off": 4,
            "notes": "QuickTime ftyp box, major brand qt  "},
    # JCAMP-DX family: JCM (325), JDX (326) and DX (160) are the same
    # text format under three extensions; all begin ##TITLE=.
    "326": {"magic": "23235449544c453d", "derivation": "text",
            "notes": "JDX is the JCAMP-DX extension (same format as JCM, task 325); the bare ## magic matched any text starting with ##"},
    "160": {"magic": "23235449544c453d", "derivation": "text",
            "notes": "DX is a JCAMP-DX extension (same format as JCM/JDX); sample begins ##TITLE="},
    # JPEG under the .JPE extension (same layout as .JPEG, task 331).
    "330": {"magic": "ffd8ff", "fields": JFIF_FIELDS,
            "notes": "JPE is the JPEG extension (same format as JPEG, task 331)"},
    # Shebang-identified scripts (longer magic beats the generic #! one).
    "450": {"magic": "23212f7573722f62696e2f656e76206e657874666c6f77",
            "derivation": "text",
            "notes": "Nextflow script; #!/usr/bin/env nextflow shebang"},
    "813": {"magic": "23212f7573722f62696e2f656e7620776f6c6672616d736372697074",
            "derivation": "text",
            "notes": "Wolfram Language script; #!/usr/bin/env wolframscript shebang"},
    # Plain-text formats that were misidentified via the bogus ## magic.
    "386": {"derivation": "text", "notes": "Markdown, plain text"},
    "531": {"derivation": "text", "notes": "PEM certificate, base64 text"},
    "570": {"derivation": "text", "notes": "Java properties file, plain text"},
    "593": {"derivation": "text", "notes": "R source, plain text"},
    "49": {"derivation": "text", "notes": "AWK source, plain text"},
    # Text formats recovered from gzipped/tarred distribution samples.
    "550": {"derivation": "text",
            "notes": "NBRF/PIR protein sequence, plain text (comment lines then > entries)"},
    "358": {"derivation": "text", "fields": [],
            "notes": "ARPA language model, plain text; sample is a partial gunzip (truncated tail)"},
    "394": {"derivation": "text", "fields": [],
            "notes": "Matrix Market, plain text (matrix.mtx extracted from the distribution tar.gz)"},
    "310": {"derivation": "text", "fields": [],
            "notes": "GNU Info, plain text (coreutils.info extracted from the distribution tar.gz)"},
    # Extension corrections: the page / sample mimetype disagrees with
    # the recorded extension.
    "498": {"ext": ".OTT",
            "notes": "page and sample mimetype confirm .OTT (OpenDocument Text Template); .OTS spreadsheet template is task 497"},
    "485": {"ext": ".OSC", "magic": "3c3f786d6c", "derivation": "text",
            "notes": "page confirms .OSC (OpenStreetMap Change, XML); the .OSB extension was wrong; sample gunzipped from .osc.gz"},
}

for k, v in NEW.items():
    ov[k] = v
with open(OV, "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)
print(f"overrides: {len(ov)} total, {len(NEW)} added/updated by this batch")
