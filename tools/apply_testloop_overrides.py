#!/usr/bin/env python3
"""apply_testloop_overrides.py — one-shot batch of hand overrides derived
from the Nov 25, 2026 test loop (542 samples: 193 pass / 234 partial /
114 fail). Every entry below was verified against a real sample file, the
task page, or the reference code block — see the notes field per entry.

Run: python3 tools/apply_testloop_overrides.py  (then: make table)
"""
import json
import os
import sys

OV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")
ov = json.load(open(OV))

NEW = {
    # --- bogus short magics that over-matched -------------------------
    # PCX is 0a05 (v5); the 1-byte 0a matched any file starting with \n.
    # (handled in gen_formats.py MAGIC_BY_EXT, not here)
    # YAML has no magic; "  " matched any indented text file.
    "855": {"magic": None, "derivation": "text",
            "notes": "YAML has no magic; the two-space 'magic' matched any indented text"},
    # .H: the #include 'magic' matched any C/C++ file; a header is text.
    "278": {"magic": None, "fields": [], "derivation": "text",
            "notes": "C header, plain text; the #include 'magic' matched any C/C++ file"},
    # --- container magics for formats whose code gave none ------------
    # (most go through MAGIC_BY_EXT; these need field fixes too)
    "258": {"magic": "504b0304", "fields": [],
            "notes": "GeoGebra is a ZIP; the code's 'images/' magic was a path fragment"},
    "427": {"fields": [],
            "notes": "MuseScore compressed score is a ZIP; the struct fields were counts, not offsets"},
    "25": {"fields": [],
           "notes": "RIFF WAVE-EX with an AMBG chunk; top-level decode is the RIFF header"},
    "112": {"fields": [],
            "notes": "CRAI is a gzipped TSV index; gzip wrapper identified, entries are ITF8-encoded (no fixed offsets)"},
    "765": {"fields": [],
            "notes": "VirtualBox extension pack is a gzipped tar; gzip wrapper identified, tar header fields do not apply to the compressed bytes"},
    # --- text formats (identified by extension / a text magic) --------
    "107": {"derivation": "text", "notes": "C++ source, plain text"},
    "17": {"derivation": "text", "notes": "Agda source, plain text"},
    "71": {"derivation": "text", "fields": [],
           "notes": "BYU geometry is ASCII fixed-width text"},
    "97": {"derivation": "text", "fields": [],
           "notes": "ASCII COB variant (sample is ASCII); binary COB has no distinguishing magic"},
    "748": {"derivation": "text", "fields": [],
            "notes": "Universal File Format is ASCII text, -1-delimited datasets"},
    "820": {"derivation": "text", "notes": "WordStar document, plain text"},
    "281": {"derivation": "text", "notes": "HTTP Archive, JSON"},
    "305": {"derivation": "text",
            "notes": "Siebel EIM config, INI-like text; the sample on disk is a DOCX and needs replacing"},
    "652": {"magic": None, "fields": [], "derivation": "text",
            "notes": "SpecsIntact .SEC is SGML-like text, not a ZIP"},
    "580": {"fields": [], "derivation": "text",
            "notes": "PTF is XML; the struct fields were counts, not file offsets"},
    # --- shebang / line-start magics ----------------------------------
    "556": {"magic": "23212f7573722f62696e2f7065726c", "derivation": "text",
            "notes": "Perl script; #!/usr/bin/perl shebang (env-perl scripts fall back to extension)"},
    "368": {"magic": "234558544d3355", "derivation": "text",
            "notes": "page is titled .MCU but the content and sample are an M3U playlist (#EXTM3U); .M3U8 is task 369"},
    "325": {"magic": "23235449544c453d", "derivation": "text",
            "notes": "JCAMP-DX; files begin ##TITLE=; the bare ## magic matched any text starting with ##"},
    "298": {"magic": "424547494e3a5643414c454e444152", "derivation": "text",
            "notes": "iCalendar, RFC 5545; files begin BEGIN:VCALENDAR"},
    # --- real magics + corrected layouts ------------------------------
    "29": {"magic": "2321414d52",
           "fields": [{"name": "magic", "offset": 0, "size": 6, "kind": "ascii"},
                      {"name": "first_frame_header", "offset": 6, "size": 1, "kind": "u8"}],
           "notes": "AMR narrowband and wideband share the #!AMR prefix; the code's WB-only magic missed NB files"},
    "66": {"magic": "42505331",
           "notes": "BPS1; after the magic the header is variable-length ints, so no fixed layout"},
    "81": {"magic": "52494646", "fields": [],
           "notes": "CorelDRAW pre-X4 RIFF variant; X4+ ZIP variant is task 82"},
    "82": {"magic": "504b0304", "fields": [],
           "notes": "CorelDRAW X4+ ZIP variant; pre-X4 RIFF variant is task 81"},
    "94": {"magic": "2363656c6d6f64656c5f62696e617279",
           "fields": [{"name": "magic", "offset": 0, "size": 16, "kind": "ascii"},
                      {"name": "materialCount", "offset": 16, "size": 4, "kind": "u32"}],
           "notes": "binary CMOD; 16-byte #celmodel_binary header then counts (meshCount follows the variable materials array)"},
    "95": {"magic": "2363656c6d6f64656c5f5f6173636969", "fields": [],
           "derivation": "text",
           "notes": "ASCII CMOD; binary variant is task 94"},
    "113": {"magic": "43363420434152545249444745",
            "fields": [{"name": "signature", "offset": 0, "size": 16, "kind": "ascii"},
                       {"name": "header_length", "offset": 16, "size": 4, "kind": "u32"},
                       {"name": "version", "offset": 20, "size": 2, "kind": "u16"},
                       {"name": "hardware_type", "offset": 22, "size": 2, "kind": "u16"},
                       {"name": "exrom", "offset": 24, "size": 1, "kind": "u8"},
                       {"name": "game", "offset": 25, "size": 1, "kind": "u8"},
                       {"name": "revision", "offset": 26, "size": 1, "kind": "u8"},
                       {"name": "reserved", "offset": 27, "size": 5, "kind": "bytes"},
                       {"name": "name", "offset": 32, "size": 32, "kind": "ascii"},
                       {"name": "chip_sig", "offset": 64, "size": 4, "kind": "ascii"},
                       {"name": "packet_len", "offset": 68, "size": 4, "kind": "u32"},
                       {"name": "chip_type", "offset": 72, "size": 2, "kind": "u16"},
                       {"name": "bank", "offset": 74, "size": 2, "kind": "u16"},
                       {"name": "load_addr", "offset": 76, "size": 2, "kind": "u16"},
                       {"name": "image_size", "offset": 78, "size": 2, "kind": "u16"}],
            "notes": "C64 cartridge; struct sizes carried NUL slots (signature 17 not 16, name 33 not 32), offsets corrected"},
    "142": {"magic": "4d444d50",
            "notes": "Windows minidump; header fields from the reference struct"},
    "193": {"magic": "455534617665496e4d28",
            "notes": "EU4 binary save magic 'EUSaveInM('; no fixed header layout beyond the magic"},
    "282": {"magic": "0e031301",
            "fields": [{"name": "tag", "offset": 4, "size": 2, "kind": "u16"},
                       {"name": "ref", "offset": 6, "size": 2, "kind": "u16"},
                       {"name": "offset", "offset": 8, "size": 4, "kind": "u32"},
                       {"name": "length", "offset": 12, "size": 4, "kind": "u32"}],
            "endian": "be",
            "notes": "page is titled .HAR but the content and sample are HDF4 (Hierarchical Data Format v4); first data descriptor follows the 4-byte signature"},
    "299": {"magic": "6d6e7472", "magic_off": 12, "endian": "be",
            "fields": [{"name": "profile_size", "offset": 0, "size": 4, "kind": "u32"},
                       {"name": "cmm_signature", "offset": 4, "size": 4, "kind": "ascii"},
                       {"name": "version", "offset": 8, "size": 4, "kind": "u32"},
                       {"name": "device_class", "offset": 12, "size": 4, "kind": "ascii"},
                       {"name": "color_space", "offset": 16, "size": 4, "kind": "ascii"},
                       {"name": "pcs", "offset": 20, "size": 4, "kind": "ascii"}],
            "notes": "page is titled .ICAL but the content and sample are an ICC color profile (display class 'mntr' at offset 12; other classes fall back to extension)"},
    "338": {"ext": ".JXL", "magic": "0000000c4a584c200d0a870a", "magic_off": 0,
            "endian": "be",
            "fields": [{"name": "signature", "offset": 0, "size": 12, "kind": "bytes"},
                       {"name": "box_size", "offset": 12, "size": 4, "kind": "u32"},
                       {"name": "box_type", "offset": 16, "size": 4, "kind": "ascii"},
                       {"name": "major_brand", "offset": 20, "size": 4, "kind": "ascii"}],
            "name": "JPEG XL image",
            "notes": "page is titled .JVX but the code, spec and sample are JPEG XL (ISO/IEC 18181)"},
    "364": {"magic": "464f524d",
            "notes": "LightWave Object is IFF FORM; the sample on disk is a RAR and needs replacing"},
    "387": {"magic": "000100005374616e64617264204a6574",
            "fields": [{"name": "signature", "offset": 0, "size": 16, "kind": "bytes"},
                       {"name": "jet_version", "offset": 20, "size": 1, "kind": "u8"},
                       {"name": "file_type", "offset": 21, "size": 1, "kind": "u8"},
                       {"name": "sys_collation", "offset": 22, "size": 2, "kind": "u16"},
                       {"name": "code_page", "offset": 28, "size": 2, "kind": "u16"},
                       {"name": "db_key", "offset": 30, "size": 4, "kind": "u32"}],
            "notes": "Jet database; header offsets from the reference code (its numPages@8 reads inside the magic and is omitted)"},
    "69": {"fields": [{"name": "total_length", "offset": 0, "size": 4, "kind": "u32"},
                      {"name": "first_element_type", "offset": 4, "size": 1, "kind": "u8"}],
           "notes": "BSON has no magic; documents begin with a 4-byte total length"},
    "696": {"magic": "53544f52",
            "fields": [{"name": "signature", "offset": 0, "size": 4, "kind": "ascii"},
                       {"name": "version", "offset": 4, "size": 4, "kind": "ascii"},
                       {"name": "type", "offset": 8, "size": 4, "kind": "u32"},
                       {"name": "name", "offset": 12, "size": 4, "kind": "u32"},
                       {"name": "flags", "offset": 16, "size": 4, "kind": "u32"},
                       {"name": "sell_markup", "offset": 20, "size": 4, "kind": "u32"},
                       {"name": "buy_markup", "offset": 24, "size": 4, "kind": "u32"},
                       {"name": "depreciation", "offset": 28, "size": 4, "kind": "u32"},
                       {"name": "steal_failure", "offset": 32, "size": 2, "kind": "u16"},
                       {"name": "capacity", "offset": 34, "size": 2, "kind": "u16"},
                       {"name": "unknown1", "offset": 36, "size": 8, "kind": "bytes"},
                       {"name": "purchased_offset", "offset": 44, "size": 4, "kind": "u32"},
                       {"name": "purchased_count", "offset": 48, "size": 4, "kind": "u32"},
                       {"name": "items_offset", "offset": 52, "size": 4, "kind": "u32"},
                       {"name": "items_count", "offset": 56, "size": 4, "kind": "u32"},
                       {"name": "drinks_offset", "offset": 76, "size": 4, "kind": "u32"},
                       {"name": "drinks_count", "offset": 80, "size": 4, "kind": "u32"},
                       {"name": "cures_offset", "offset": 112, "size": 4, "kind": "u32"},
                       {"name": "cures_count", "offset": 116, "size": 4, "kind": "u32"}],
            "notes": "Infinity Engine store file (Baldur's Gate); signature STOR + version V1.1; OpenSim text .STO is task 695"},
}

for k, v in NEW.items():
    ov[k] = v
with open(OV, "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)
print(f"overrides: {len(ov)} total, {len(NEW)} added/updated by this batch")
