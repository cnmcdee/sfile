#!/usr/bin/env python3
"""gen_formats.py — derive sfile's format table from the collected C/C++
reference code (tools/all_formats.cpp).

The reference blocks are heterogeneous, but the dominant pattern for a
binary format is:

    typedef struct { char magic[5]; uint16_t version; ... } XProperties;
    void read_...(FILE *f, XProperties *props) {
        char magic[4]; fread(magic, 1, 4, f); strncpy(props->magic, magic, 4);
        fread(&props->version, sizeof(uint16_t), 1, f);
        ...
    }

So the RELIABLE extraction is the sequential read sequence in the read
function: each fread/file.read gives (target field, on-disk byte count),
and offsets are cumulative in read order. The struct supplies the field
NAMES and TYPES; the read sequence supplies the true on-disk SIZES
(which differ from the struct when a char[N] carries a NUL slot, e.g.
magic[5] in the struct but 4 bytes on disk). fseek(f, N, SEEK_SET)
before a read gives an ABSOLUTE offset for that field.

Derivation labels (recorded per format so the test loop can target
the weak entries):
    readseq   — fields + offsets from a parsed sequential read sequence
                (highest confidence)
    struct    — struct fields in order, sizes from C types, offsets
                sequential (no read function found to confirm sizes)
    explicit  — C++ class reading data[N] / data + N with named properties
    text      — XML/JSON/text format; no binary header (text decoder)
    magic-only— a magic signature was found but no fixed field layout
    unknown   — nothing derivable; needs a hand override or an
                "unsupported" report

Magic is extracted from string-literal comparisons against the file's
first bytes:  sig != "..." / memcmp(..., "...", n) / strcmp(sig, "...") /
strncmp / a `char signature[N]` field plus a literal. C escapes
(\\xNN, \\0, \\n, ...) are decoded to real bytes. The first struct/read
field named magic/signature is also used: its on-disk bytes are the magic
only when the code compares them to a literal (otherwise the magic is
left empty and the test loop fills it from a verified sample).

Output:
  src/formats.json — per-format table (source of truth; hand overrides in
                     tools/overrides.json are applied on top)
  src/formats.h    — generated C table for the sfile engine

Usage:
    ./gen_formats.py [all_formats.cpp] [out_json] [out_h]
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CPP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "all_formats.cpp")
OUT_JSON = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRIPT_DIR, "..", "src", "formats.json")
OUT_H = sys.argv[3] if len(sys.argv) > 3 else os.path.join(SCRIPT_DIR, "..", "src", "formats.h")
OVERRIDES = os.path.join(SCRIPT_DIR, "overrides.json")

TYPE_MAP = {
    "char": (1, "ascii"), "int8_t": (1, "i8"), "uint8_t": (1, "u8"),
    "unsigned char": (1, "u8"), "int16_t": (2, "i16"), "uint16_t": (2, "u16"),
    "short": (2, "i16"), "unsigned short": (2, "u16"),
    "int32_t": (4, "i32"), "uint32_t": (4, "u32"),
    "int": (4, "i32"), "unsigned int": (4, "u32"), "long": (4, "i32"),
    "int64_t": (8, "i64"), "uint64_t": (8, "u64"),
    "long long": (8, "i64"), "unsigned long long": (8, "u64"),
    "float": (4, "f32"), "double": (8, "f64"),
}
SIZEOF_MAP = {"uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
              "uint32_t": 4, "int32_t": 4, "uint64_t": 8, "int64_t": 8,
              "char": 1, "short": 2, "int": 4, "long": 4, "float": 4,
              "double": 8, "unsigned char": 1, "unsigned short": 2,
              "unsigned int": 4, "unsigned long": 4, "long long": 8,
              "unsigned long long": 8}
SKIP_FIELDS = {"file_size", "is_riff", "is_valid", "filesize", "size",
               "is_zip", "is_big_endian", "is_little_endian", "has_extended",
               "file", "filename", "filepath", "data", "buffer"}

FIELD_RE = re.compile(
    r"^\s*(unsigned\s+char|unsigned\s+short|unsigned\s+int|unsigned\s+long\s+long|"
    r"long\s+long|char|int8_t|uint8_t|int16_t|uint16_t|int32_t|uint32_t|"
    r"int64_t|uint64_t|int|short|long|float|double|size_t|bool|std::string|std::vector<[^>]+>)\s+"
    r"(\w+)\s*(?:\[\s*(\d+)\s*\])?\s*(?:=\s*[^;]*)?;", re.M)

def parse_structs(body):
    """All struct definitions -> {field_name: (ctype, array_N or None)}.
    Prefers the *Properties struct for name lookups, but returns every
    struct's fields merged (first definition wins per name)."""
    fmap = {}
    # typedef struct { ... } Name;
    for m in re.finditer(r"typedef\s+struct\s*(?:\w+\s*)?\{(.*?)\}\s*(\w+)\s*;", body, re.S):
        struct_body, sname = m.group(1), m.group(2)
        for fm in FIELD_RE.finditer(struct_body):
            ctype, name, arr = fm.group(1), fm.group(2), fm.group(3)
            if name not in fmap:
                fmap[name] = (ctype, int(arr) if arr else None, sname)
    # struct Name { ... };
    for m in re.finditer(r"(?<!typedef\s)\bstruct\s+(\w+)\s*\{(.*?)\}\s*;", body, re.S):
        sname, struct_body = m.group(1), m.group(2)
        for fm in FIELD_RE.finditer(struct_body):
            ctype, name, arr = fm.group(1), fm.group(2), fm.group(3)
            if name not in fmap:
                fmap[name] = (ctype, int(arr) if arr else None, sname)
    return fmap

def field_kind_size(ctype, arr, fmap_name=None):
    """(size, kind) for a struct field. char[N] on disk is N bytes unless
    the read sequence says otherwise (handled by the caller)."""
    base = TYPE_MAP.get(ctype)
    if base is None:
        return None
    size, kind = base
    if arr:
        size = size * arr
        kind = "ascii" if ctype in ("char", "unsigned char") else "bytes"
    return (size, kind)

# ---- read-sequence parsing -------------------------------------------
# The common C pattern reads into a TEMP then assigns to the struct:
#     uint32_t val; fread(&val, sizeof(uint32_t), 1, f); props->field = val;
# so we track temp reads and pair each with the NEXT assignment to a
# props field. Direct props reads (fread(&props->x,...)) are also handled,
# as are buf+strcpy (char[N] with a NUL slot) and memcpy(&x, buf, N).
FREAD_PROPS = re.compile(
    r"""fread\s*\(\s*&\s*([\w\-.>]+?)\s*,\s*(?:sizeof\s*\(\s*(\w+)\s*\)|(\d+))\s*,\s*1\s*,""")
FREAD_BUF = re.compile(
    r"""fread\s*\(\s*(\w+)\s*,\s*1\s*,\s*(\d+)\s*,""")
STRNCPY = re.compile(
    r"""strn?cpy\s*\(\s*([\w\-.>]+?)\s*,\s*(?:\(\s*char\s*\*\s*\)\s*)?(\w+)\s*(?:,\s*(\d+))?\s*\)""")
FILEREAD = re.compile(
    r"""\.read\s*\(\s*reinterpret_cast<char\s*\*>\s*\(\s*&\s*(\w+)\s*\)\s*,\s*(?:sizeof\s*\(\s*(\w+)\s*\)|(\d+))\s*\)""")
FILEREAD2 = re.compile(
    r"""\.read\s*\(\s*reinterpret_cast<char\s*\*>\s*\(\s*&\s*(?:\w+\.)?(\w+)\s*\)\s*,\s*(?:sizeof\s*\(\s*(\w+)\s*\)|(\d+))\s*\)""")
FSEEK = re.compile(r"""fseek\s*\(\s*\w+\s*,\s*(\d+)\s*,\s*SEEK_SET\s*\)""")
MEMCPY_OFF = re.compile(
    r"""memcpy\s*\(\s*&\s*(\w+)\s*,\s*(?:buffer|data)\s*\+\s*(\d+)\s*,\s*(\d+)\s*\)""")
MEMCPY_BUF = re.compile(
    r"""memcpy\s*\(\s*&\s*([\w\-.>]+?)\s*,\s*(\w+)\s*,\s*(\d+)\s*\)""")

def last_component(expr):
    return re.split(r'->|\.', expr)[-1].strip()

def _kind_for(fname, size, fmap):
    if fname in fmap:
        ctype, arr, _ = fmap[fname]
        kk = field_kind_size(ctype, arr)
        if kk:
            return kk[1]
    if size in (1, 2, 4, 8):
        return "u%d" % (size * 8)
    return "bytes"

def derive_readseq(body, fmap):
    """Parse the sequential read sequence. Returns (fields, derivation)
    where fields = [{name, offset, size, kind}]."""
    events = []
    for m in FREAD_PROPS.finditer(body):
        tgt = m.group(1)
        name = last_component(tgt)
        size = SIZEOF_MAP.get(m.group(2)) if m.group(2) else int(m.group(3))
        if size is None:
            continue
        if name in fmap:
            events.append((m.start(), "read", name, size))
        else:
            events.append((m.start(), "temp", name, size))
    for m in FREAD_BUF.finditer(body):
        events.append((m.start(), "buf", m.group(1), int(m.group(2))))
    for m in STRNCPY.finditer(body):
        events.append((m.start(), "copy", m.group(0), 0))
    for m in FILEREAD.finditer(body):
        size = SIZEOF_MAP.get(m.group(2)) if m.group(2) else int(m.group(3))
        if size is not None:
            events.append((m.start(), "read", m.group(1), size))
    for m in FILEREAD2.finditer(body):
        size = SIZEOF_MAP.get(m.group(2)) if m.group(2) else int(m.group(3))
        if size is not None:
            events.append((m.start(), "read", m.group(1), size))
    for m in MEMCPY_OFF.finditer(body):
        events.append((m.start(), "absoff", m.group(1), (int(m.group(2)), int(m.group(3)))))
    for m in MEMCPY_BUF.finditer(body):
        events.append((m.start(), "memcpybuf", m.group(0), 0))
    for m in FSEEK.finditer(body):
        events.append((m.start(), "seek", None, int(m.group(1))))
    if not events:
        return None, None
    events.sort(key=lambda e: e[0])

    fields = []
    offset = 0
    pending_buf = {}   # buf var -> (offset, size)
    seen = set()
    for pos, kind, name, size in events:
        if kind == "seek":
            offset = size
        elif kind == "buf":
            pending_buf[name] = (offset, size)
            offset += size
        elif kind == "temp":
            offset += size
        elif kind == "copy":
            mm = re.search(r'strn?cpy\s*\(\s*([\w\-.>]+?)\s*,\s*(?:\(\s*char\s*\*\s*\)\s*)?(\w+)', name)
            if not mm:
                continue
            fname = last_component(mm.group(1))
            buf = mm.group(2)
            if buf in pending_buf and fname not in seen and fname not in SKIP_FIELDS:
                boff, bsize = pending_buf[buf]
                mn = re.search(r'strn?cpy\s*\([^,]+,[^,]+,\s*(\d+)\s*\)', name)
                n = int(mn.group(1)) if mn else bsize
                k = "ascii"
                if fname in fmap:
                    ctype, arr, _ = fmap[fname]
                    k = "ascii" if ctype in ("char", "unsigned char") else "bytes"
                fields.append({"name": fname, "offset": boff, "size": n, "kind": k})
                seen.add(fname)
        elif kind == "memcpybuf":
            mm = re.search(r'memcpy\s*\(\s*&\s*([\w\-.>]+?)\s*,\s*(\w+)\s*,\s*(\d+)\s*\)', name)
            if not mm:
                continue
            fname = last_component(mm.group(1))
            buf, n = mm.group(2), int(mm.group(3))
            if buf in pending_buf and fname not in seen and fname not in SKIP_FIELDS:
                boff, _ = pending_buf[buf]
                fields.append({"name": fname, "offset": boff, "size": n,
                               "kind": _kind_for(fname, n, fmap)})
                seen.add(fname)
        elif kind == "absoff":
            fname = name
            aoff, n = size
            if fname not in seen and fname not in SKIP_FIELDS:
                fields.append({"name": fname, "offset": aoff, "size": n,
                               "kind": _kind_for(fname, n, fmap)})
                seen.add(fname)
        elif kind == "read":
            fname = name
            if fname in seen or fname in SKIP_FIELDS:
                continue
            fields.append({"name": fname, "offset": offset, "size": size,
                           "kind": _kind_for(fname, size, fmap)})
            seen.add(fname)
            offset += size
    fields = pair_temp_assignments(body, events, fields, fmap, seen)
    if not fields or len(fields) < 2:
        return None, None
    fields.sort(key=lambda f: f["offset"])
    return fields, "readseq"

def pair_temp_assignments(body, events, fields, fmap, seen):
    """For each 'temp' event (fread into a local var), find the assignment
    of that var to a props field and emit a field entry."""
    out = list(fields)
    offset = 0
    pending = []
    for pos, kind, name, size in events:
        if kind == "seek":
            offset = size
        elif kind in ("buf", "temp", "read"):
            if kind == "temp":
                pending.append((name, size, offset))
            if isinstance(size, int):
                offset += size
    for temp, size, off in pending:
        pat = re.compile(
            r"""(?:props?|parser->props|parser->properties|p|hdr|header)(?:->|\.)\s*(\w+)\s*=\s*"""
            r"""(?:\(\s*\w+\s*\)\s*)?(?:\w+\s*\(\s*)?""" + re.escape(temp) + r"""\b""")
        m = pat.search(body)
        if not m:
            continue
        fname = m.group(1)
        if fname in seen or fname in SKIP_FIELDS:
            continue
        out.append({"name": fname, "offset": off, "size": size,
                    "kind": _kind_for(fname, size, fmap)})
        seen.add(fname)
    return out


def parse_explicit(body):
    """C++ class style: properties["name"] = expr involving data+N / data[N]."""
    out = []
    pat1 = re.compile(
        r"""properties\[\s*"([^"]+)"\s*\]\s*=\s*(?:\(\s*static_cast<\w+>\s*\)\s*)?"""
        r"""\*reinterpret_cast<const\s+(u?int(?:8|16|32|64)_t)\s*\*>\s*\(\s*data\s*\+\s*(\d+)\s*\)""")
    for m in pat1.finditer(body):
        name, ctype, off = m.group(1), m.group(2), int(m.group(3))
        size = {"uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
                "uint32_t": 4, "int32_t": 4, "uint64_t": 8, "int64_t": 8}[ctype]
        out.append((name, off, size, "u%d" % (size * 8)))
    pat2 = re.compile(
        r"""properties\[\s*"([^"]+)"\s*\]\s*=\s*readUint(8|16|32|64)\s*\(\s*data\s*\+\s*(\d+)\s*\)""")
    for m in pat2.finditer(body):
        name, bits, off = m.group(1), int(m.group(2)), int(m.group(3))
        out.append((name, off, bits // 8, "u%d" % bits))
    pat3 = re.compile(
        r"""(?:uint8_t|uint16_t|uint32_t|uint64_t)\s+(\w+)\s*=\s*"""
        r"""(?:static_cast<\w+>\s*\(\s*)?data\[(\d+)\]""")
    for m in pat3.finditer(body):
        name, off = m.group(1), int(m.group(2))
        out.append((name, off, 1, "u8"))
    # Two-step: TYPE var = *reinterpret_cast<const T*>(data + N);
    #           properties["name"] = var;
    pat4 = re.compile(
        r"""(?:uint8_t|uint16_t|uint32_t|uint64_t|int8_t|int16_t|int32_t|int64_t)\s+(\w+)\s*=\s*"""
        r"""\*reinterpret_cast<const\s+(u?int(?:8|16|32|64)_t)\s*\*>\s*\(\s*data\s*\+\s*(\d+)\s*\)""")
    pat4b = re.compile(
        r"""(?:uint8_t|uint16_t|uint32_t|uint64_t)\s+(\w+)\s*=\s*readUint(8|16|32|64)\s*\(\s*data\s*\+\s*(\d+)\s*\)""")
    varmap = {}
    for m in pat4.finditer(body):
        var, ctype, off = m.group(1), m.group(2), int(m.group(3))
        size = {"uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
                "uint32_t": 4, "int32_t": 4, "uint64_t": 8, "int64_t": 8}[ctype]
        varmap[var] = (off, size)
    for m in pat4b.finditer(body):
        var, bits, off = m.group(1), int(m.group(2)), int(m.group(3))
        varmap[var] = (off, bits // 8)
    pat5 = re.compile(r"""properties\[\s*"([^"]+)"\s*\]\s*=\s*(\w+)\s*;""")
    for m in pat5.finditer(body):
        name, var = m.group(1), m.group(2)
        if var in varmap:
            off, size = varmap[var]
            out.append((name, off, size, "u%d" % (size * 8)))
    # data[N] char comparisons for a signature: string(data, N) == "..."
    seen = set()
    res = []
    for item in sorted(out, key=lambda x: x[1]):
        if (item[0], item[1]) not in seen:
            seen.add((item[0], item[1]))
            res.append({"name": item[0], "offset": item[1], "size": item[2], "kind": item[3]})
    return res or None

MAGIC_PATTERNS = [
    re.compile(r"""\bsig(?:nature)?\s*(?:!=|==)\s*"((?:[^"\\]|\\.)*)\""""),
    re.compile(r"""memcmp\s*\([^,]+,\s*"((?:[^"\\]|\\.)*)"\s*,"""),
    re.compile(r"""strncmp?\s*\([^,]+,\s*"((?:[^"\\]|\\.)*)\""""),
    re.compile(r"""string\s*\(\s*data\s*,\s*\d+\s*\)\s*(?:!=|==)\s*"((?:[^"\\]|\\.)*)\""""),
    re.compile(r"""std::string\s+sig\s*\(\s*data\s*,\s*\d+\s*\)\s*;[^}]{0,200}?sig\s*(?:!=|==)\s*"((?:[^"\\]|\\.)*)\"""", re.S),
]

def decode_c_string(lit):
    out = bytearray()
    i = 0
    while i < len(lit):
        c = lit[i]
        if c != "\\":
            out.append(ord(c)); i += 1; continue
        i += 1
        if i >= len(lit):
            return None
        e = lit[i]
        if e == "x":
            m = re.match(r"[0-9a-fA-F]{1,2}", lit[i + 1:i + 3])
            if not m:
                return None
            out.append(int(m.group(0), 16)); i += 1 + len(m.group(0))
        elif e in "01234567":
            m = re.match(r"[0-7]{1,3}", lit[i:i + 3])
            out.append(int(m.group(0), 8) & 0xFF); i += len(m.group(0))
        elif e == "n": out.append(10); i += 1
        elif e == "r": out.append(13); i += 1
        elif e == "t": out.append(9); i += 1
        elif e == "0": out.append(0); i += 1
        elif e == "\\": out.append(92); i += 1
        elif e == '"': out.append(34); i += 1
        elif e == "'": out.append(39); i += 1
        else: return None
    return bytes(out)

def find_magic(body):
    best = None
    for pat in MAGIC_PATTERNS:
        for m in pat.finditer(body):
            b = decode_c_string(m.group(1))
            if b and len(b) >= 2:
                if best is None or len(b) > len(best[0]):
                    best = (b, 0)
    return best

# Curated magic bytes for well-known formats, keyed by extension.
# These are standard, published file signatures (not guesses). They are
# applied ONLY when the reference code yielded no magic, and the test
# loop verifies each one against a real sample file. Value is a hex
# string, or (hex, offset) for magics that are not at offset 0.
MAGIC_BY_EXT = {
    ".PNG": "89504e470d0a1a0a",
    ".JPG": "ffd8ff", ".JPEG": "ffd8ff",
    ".GIF": "47494638",
    ".ZIP": "504b0304",
    ".7Z": "377abcaf271c",
    ".PDF": "25504446",
    ".ELF": "7f454c46",
    ".EXE": "4d5a", ".DLL": "4d5a", ".COM": "4d5a",
    ".GZ": "1f8b", ".TGZ": "1f8b",
    ".BZ2": "425a68",
    ".XZ": "fd377a585a00",
    ".ZST": "28b52ffd",
    ".WAV": "52494646", ".AVI": "52494646",
    ".BMP": "424d",
    ".ICO": "00000100", ".CUR": "00000200",
    ".MP3": "494433", ".MP4": None, ".MOV": None,
    ".FLAC": "664c6143",
    ".OGG": "4f676753",
    ".WEBP": "52494646",
    ".TIFF": "49492a00", ".TIF": "49492a00",
    ".PSD": "38425053",
    ".AI": "25504446",
    ".EPS": "c5d0d3c6",
    ".CLASS": "cafebabe",
    ".JAR": "504b0304",
    ".APK": "504b0304",
    ".DOCX": "504b0304", ".XLSX": "504b0304", ".PPTX": "504b0304",
    ".ODT": "504b0304", ".ODS": "504b0304", ".ODP": "504b0304",
    ".EPUB": "504b0304",
    ".RAR": "526172211a0700",
    ".ARJ": "60ea",
    ".CAB": "4d534346",
    ".DMG": "6b6f6c79",
    ".ISO": ("4344303031", 32769),
    ".TAR": ("7573746172", 257),
    ".WASM": "0061736d",
    ".SQLITE": "53514c69746520666f726d6174203300",
    ".DB": "53514c69746520666f726d6174203300",
    ".SWF": "465753",
    ".FLV": "464c56",
    ".MKV": "1a45dfa3", ".WEBM": "1a45dfa3",
    ".MID": "4d546864", ".MIDI": "4d546864",
    ".TTF": "00010000", ".OTF": "4f54544f",
    ".WOFF": "774f4646", ".WOFF2": "774f4632",
    ".RTF": "7b5c727466",
    ".XML": "3c3f786d6c",
    ".HTML": None, ".HTM": None,
    ".JSON": None,
    ".CSV": None, ".TXT": None,
    ".PY": None, ".C": None, ".CPP": None, ".H": None, ".JS": None,
    ".CHM": "49545346",
    ".MSI": "d0cf11e0a1b11ae1",
    ".DOC": "d0cf11e0a1b11ae1", ".XLS": "d0cf11e0a1b11ae1", ".PPT": "d0cf11e0a1b11ae1",
    ".DS_STORE": None,
    ".LZH": None, ".LHA": None,
    ".ACE": "2a2a4143452a2a",
    ".SIT": None,
    ".SEA": None,
    ".HQX": None,
    ".UU": None,
    ".UUE": None,
    ".XXE": None,
    ".B64": None,
    ".MIME": None,
    ".EML": None,
    ".MBOX": None,
    ".PST": "2142444e",
    ".OST": "2142444e",
    ".MSG": "d0cf11e0a1b11ae1",
    ".PST2": None,
    ".VCF": None, ".ICS": None, ".ICAL": None,
    ".AB": None,
    ".BAK": None,
    ".TMP": None,
    ".LOG": None,
    ".INI": None, ".CFG": None, ".CONF": None,
    ".YAML": None, ".YML": None, ".TOML": None,
    ".MD": None,
    ".SVG": "3c737667",
    ".XSL": "3c3f786d6c",
    ".XSLT": "3c3f786d6c",
    ".DTD": None,
    ".XSD": "3c3f786d6c",
    ".RDF": "3c3f786d6c",
    ".RSS": "3c3f786d6c",
    ".ATOM": "3c3f786d6c",
    ".OPML": "3c3f786d6c",
    ".KML": "3c3f786d6c",
    ".GPX": "3c3f786d6c",
    ".PLIST": "3c3f786d6c",
    ".PBM": "5031", ".PGM": "5032", ".PPM": "5033", ".PNM": "5031",
    ".TGA": "00000200", ".VDA": "00000200", ".WKS": "00000200",
    ".PI2": "00010000",
    ".LZ": "4c5a4950", ".GRB": "47524942", ".SFX": "4d5a",
    ".G4": "49492a00",
    ".PCX": "0a05",
    ".EMZ": "1f8b", ".RDS": "1f8b", ".VBOXEXTPACK": "1f8b",
    ".CRAI": "1f8b", ".PET": "1f8b", ".XP": "1f8b",
    ".R01": "526172211a0700", ".ROO": "526172211a0700",
    ".DDS": "44445320",
    ".KTX": "ab4b5458203131",
    ".EXR": "762f3102",
    ".HDR": "233f52414449414e4345",
    ".CR2": "49492a00",
    ".NEF": "4d4d002a",
    ".ORF": "4949524f",
    ".DNG": "49492a00",
    ".RAF": "46554a4946494c4d",
    ".RW2": "49494900",
    ".SRF": None,
    ".ARW": "49492a00",
    ".PEF": "4d4d002a",
    ".X3F": "464f5645",
    ".HEIC": None, ".HEIF": None,
    ".AVIF": None,
    ".JP2": "0000000c6a502020", ".J2K": "ff4fff51",
    ".JXR": "49495502", ".HDP": "49495502",
    ".WEBP2": None,
    ".FLIF": "464c4946",
    ".QOI": "66696f71",
    ".KTX2": "ab4b5458203230",
    ".ASTC": "13ab a1 5c".replace(" ", ""),
    ".PVR": "50565203",
    ".SCT": None,
    ".MNG": "8a4d4e470d0a1a0a",
    ".JNG": "8b4a4e470d0a1a0a",
    ".APNG": "89504e470d0a1a0a",
    ".ICO2": None,
    ".ICNS": "69636e73",
    ".CUR2": None,
    ".ANI": "52494646",
    ".DIB": None,
    ".EMF": "01000000",
    ".WMF": "d7cdc69a",
    ".CGM": "0040",
    ".SVGZ": "1f8b",
    ".PDF2": "25504446",
    ".XPS": "504b0304",
    ".OXPS": "504b0304",
    ".CBZ": "504b0304", ".CBR": "526172211a0700", ".CB7": "377abcaf271c",
    ".CBT": None,
    ".DJVU": "415426544f524d", ".DJV": "415426544f524d",
    ".CHM2": "49545346",
    ".LIT": "49544f4c",
    ".MOBI": None,
    ".AZW": None, ".AZW3": None,
    ".FB2": "3c3f786d6c",
    ".LRF": None, ".LRX": None,
    ".PDB": None,
    ".TCR": None,
    ".PML": None,
    ".SNB": None,
    ".RB": None,
    ".IMP": None,
    ".EBA": None,
    ".EBO": None,
    ".VEB": None,
    ".CEB": None,
    ".XEB": None,
    ".BBeB": None,
    ".PRC": None,
    ".AZW4": None,
    ".KFX": None,
    ".TPZ": "504b0304",
    ".IBA": None,
    ".IBOOKS": "504b0304",
    ".EPUB3": "504b0304",
    # --- container families (added after the first test loop) ---
    # ZIP-based (PK\x03\x04): every OpenDocument / Office Open XML /
    # EPUB / APK / JAR-family format shares this magic.
    ".NUMBERS": "504b0304", ".ODB": "504b0304", ".ODF": "504b0304",
    ".ODG": "504b0304", ".PAGES": "504b0304",
    ".KEY": "504b0304", ".KMZ": "504b0304", ".NUPKG": "504b0304",
    ".VSIX": "504b0304", ".WHL": "504b0304", ".CRX": "504b0304",
    ".XPI": "504b0304", ".OXT": "504b0304", ".OTP": "504b0304",
    ".OTG": "504b0304", ".SXW": "504b0304", ".STW": "504b0304",
    ".SXD": "504b0304", ".SXI": "504b0304", ".SXC": "504b0304",
    ".SXG": "504b0304", ".SXM": "504b0304", ".VSDX": "504b0304",
    ".VSSX": "504b0304", ".VSTX": "504b0304", ".DOCM": "504b0304",
    ".XLSM": "504b0304", ".PPTM": "504b0304", ".DOTX": "504b0304",
    ".XLTX": "504b0304", ".POTX": "504b0304", ".DOTM": "504b0304",
    ".XLTM": "504b0304", ".POTM": "504b0304", ".XLSB": "504b0304",
    ".SLDX": "504b0304", ".ONEPKG": "504b0304",
    ".UOT": "504b0304",
    ".WAR": "504b0304", ".EAR": "504b0304", ".OXPS": "504b0304",
    ".OSK": "504b0304",
    ".XPI2": "504b0304",
    # OLE compound document (d0cf11e0a1b11ae1) — more formats verified
    # against real samples in the Nov 25 test loop:
    ".DGN": "d0cf11e0a1b11ae1", ".IPT": "d0cf11e0a1b11ae1",
    ".VDW": "d0cf11e0a1b11ae1",
    # Ogg container
    ".OGX": "4f676753",
    # JPEG (same format as .JPG/.JPEG, different extension)
    ".JPE": "ffd8ff",
    # More ZIP-based formats, verified against real samples / the task
    # pages in the Nov 25 test loop (each is a ZIP container):
    ".3MF": "504b0304", ".AMLX": "504b0304", ".DN": "504b0304",
    ".PMP": "504b0304", ".VPR": "504b0304", ".EU4": "504b0304",
    ".FMU": "504b0304", ".GGB": "504b0304", ".MCADDON": "504b0304",
    ".MCPACK": "504b0304", ".MCTEMPLATE": "504b0304",
    ".MSCZ": "504b0304", ".OTS": "504b0304", ".PPSX": "504b0304", ".KRA": "504b0304", ".PK3": "504b0304",
    # XML-based formats verified against real samples (all start <?xml);
    # the engine disambiguates by extension.
    ".GXL": "3c3f786d6c", ".JNLP": "3c3f786d6c", ".JVX": "3c3f786d6c",
    ".LABEL": "3c3f786d6c", ".MODULES": "3c3f786d6c",
    ".POM": "3c3f786d6c", ".PTF": "3c3f786d6c", ".SRX": "3c3f786d6c",
    ".UXF": "3c3f786d6c", ".VBOX": "3c3f786d6c", ".VDX": "3c3f786d6c",
    ".WLMP": "3c3f786d6c", ".WSC": "3c3f786d6c", ".X3D": "3c3f786d6c",
    ".XRBL": "3c3f786d6c", ".XDM": "3c3f786d6c", ".XSPF": "3c3f786d6c",
    ".GDT": "3c3f786d6c", ".VSQX": "3c3f786d6c",
    ".DAE": "3c3f786d6c", ".E2D": "3c3f786d6c", ".EP": "3c3f786d6c",
    ".OSM": "3c3f786d6c", ".OWL": "3c3f786d6c", ".GRAPHML": "3c3f786d6c",
    # OLE compound document (d0cf11e0a1b11ae1)
    ".MSO": "d0cf11e0a1b11ae1", ".VSD": "d0cf11e0a1b11ae1",
    ".VSS": "d0cf11e0a1b11ae1", ".VST": "d0cf11e0a1b11ae1",
    ".PUB": "d0cf11e0a1b11ae1", ".WPS": "d0cf11e0a1b11ae1",
    ".XLA": "d0cf11e0a1b11ae1", ".XLW": "d0cf11e0a1b11ae1",
    ".POT": "d0cf11e0a1b11ae1", ".PPS": "d0cf11e0a1b11ae1",
    ".DOT": "d0cf11e0a1b11ae1", ".XLT": "d0cf11e0a1b11ae1",
    ".MPP": "d0cf11e0a1b11ae1", ".MPT": "d0cf11e0a1b11ae1",
    ".MPX": "d0cf11e0a1b11ae1", ".WIZ": "d0cf11e0a1b11ae1",
    # XML (<?xml) — the root element, not the magic, distinguishes these;
    # the engine disambiguates by extension.
    ".NFO": "3c3f786d6c", ".NPR": "3c3f786d6c", ".FB2": "3c3f786d6c",
    ".FODS": "3c3f786d6c", ".FODT": "3c3f786d6c", ".FODP": "3c3f786d6c",
    ".SVG": "3c3f786d6c", ".XHTML": "3c3f786d6c", ".RDF": "3c3f786d6c",
    ".PLIST": "3c3f786d6c", ".CONFIG": "3c3f786d6c", ".XAML": "3c3f786d6c",
    ".RESX": "3c3f786d6c", ".XMP": "3c3f786d6c", ".CSPROJ": "3c3f786d6c",
    ".VBPROJ": "3c3f786d6c", ".SCPT": "3c3f786d6c",
    # TIFF-based (II*\0 little-endian)
    ".NRW": "49492a00", ".NEF": "49492a00", ".DNG": "49492a00",
    ".ARW": "49492a00", ".RAF": "46554a4946494c4d", ".ORF": "4949524f",
    ".RW2": "49494900", ".PEF": "4d4d002a", ".SRF": "49492a00",
    ".DCR": "49492a00", ".KDC": "4d4d002a", ".MRW": "004d524d",
    ".ERF": "49492a00", ".MEF": "4d4d002a", ".MOS": "4d4d002a",
    ".IIQ": "49494900", ".FFF": "49494900",
    # PE / MZ executables
    ".OCX": "4d5a", ".MSSTYLES": "4d5a", ".SYS": "4d5a", ".SCR": "4d5a",
    ".CPL": "4d5a", ".DRV": "4d5a", ".VXD": "4d5a", ".AX": "4d5a",
    ".TLB": "4d5a", ".OLB": "4d5a", ".MUI": "4d5a", ".EFI": "4d5a",
    ".FON": "4d5a", ".ACM": "4d5a", ".IME": "4d5a", ".PIF": "4d5a",
    # ELF object / executable
    ".O": "7f454c46", ".SO": "7f454c46", ".KO": "7f454c46",
    ".OBJ": "7f454c46", ".LO": "7f454c46",
    # FCS (flow cytometry): "FCS" + version
    ".FCS": "464353",
}
# Entries with None mean: no reliable fixed magic (text or container with
# a variable prefix); the test loop may fill these from samples.

def apply_curated_magic(entry):
    """Fill magic from the curated table if the code gave none."""
    if entry["magic"]:
        return
    v = MAGIC_BY_EXT.get(entry["ext"].upper())
    if v is None:
        return
    if isinstance(v, tuple):
        entry["magic"], entry["magic_off"] = v[0], v[1]
    else:
        entry["magic"], entry["magic_off"] = v, 0
    entry.setdefault("notes", "")
    entry["notes"] = (entry["notes"] + " curated-magic").strip()

BE_RE = re.compile(r"ntoh[ls]|read_uint\d+_be|read_be|big.?endian|_be\s*\(", re.I)

def detect_endian(body):
    return "be" if BE_RE.search(body) else "le"

def format_name(body, ext):
    """Human-readable name from the handler class/struct name, else the ext."""
    m = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:[:\{])", body)
    if m:
        n = m.group(1)
        for suf in ("Handler", "File", "Parser", "Reader", "Decoder", "Properties"):
            if n.endswith(suf) and len(n) > len(suf):
                n = n[: -len(suf)]
                break
        # split CamelCase
        n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
        n = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", n)
        if n.strip():
            return n.strip()
    m = re.search(r"typedef\s+struct\s*(?:\w+\s*)?\{(.*?)\}\s*(\w+)\s*;", body, re.S)
    if m and "ropert" in m.group(2):
        n = m.group(2).replace("Properties", "")
        n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
        if n.strip():
            return n.strip()
    return ext.lstrip(".").upper() + " file"

# Container layouts inherited by formats that share the container magic
# but have no field layout of their own. These are the fixed prefixes of
# the container, not the whole format — the point is that every ZIP file
# starts with a local file header, every RIFF file with a RIFF header,
# every ftyp file with a file-type box.
CONTAINER_LAYOUTS = {
    ("504b0304", 0): [  # ZIP local file header
        {"name": "signature", "offset": 0, "size": 4, "kind": "bytes"},
        {"name": "version_needed", "offset": 4, "size": 2, "kind": "u16"},
        {"name": "flags", "offset": 6, "size": 2, "kind": "u16"},
        {"name": "method", "offset": 8, "size": 2, "kind": "u16"},
        {"name": "mod_time", "offset": 10, "size": 2, "kind": "u16"},
        {"name": "mod_date", "offset": 12, "size": 2, "kind": "u16"},
        {"name": "crc32", "offset": 14, "size": 4, "kind": "u32"},
        {"name": "compressed_size", "offset": 18, "size": 4, "kind": "u32"},
        {"name": "uncompressed_size", "offset": 22, "size": 4, "kind": "u32"},
        {"name": "filename_len", "offset": 26, "size": 2, "kind": "u16"},
        {"name": "extra_len", "offset": 28, "size": 2, "kind": "u16"},
    ],
    ("52494646", 0): [  # RIFF header
        {"name": "signature", "offset": 0, "size": 4, "kind": "ascii"},
        {"name": "file_size", "offset": 4, "size": 4, "kind": "u32"},
        {"name": "form_type", "offset": 8, "size": 4, "kind": "ascii"},
    ],
    ("66747970", 4): [  # ISO BMFF file-type box (ftyp)
        {"name": "box_size", "offset": 0, "size": 4, "kind": "u32", "be": True},
        {"name": "box_type", "offset": 4, "size": 4, "kind": "ascii"},
        {"name": "major_brand", "offset": 8, "size": 4, "kind": "ascii"},
        {"name": "minor_version", "offset": 12, "size": 4, "kind": "u32", "be": True},
    ],
    ("4f676753", 0): [  # Ogg page header
        {"name": "capture_pattern", "offset": 0, "size": 4, "kind": "ascii"},
        {"name": "version", "offset": 4, "size": 1, "kind": "u8"},
        {"name": "header_type", "offset": 5, "size": 1, "kind": "u8"},
        {"name": "granule_position", "offset": 6, "size": 8, "kind": "u64"},
        {"name": "serial_number", "offset": 14, "size": 4, "kind": "u32"},
        {"name": "page_sequence", "offset": 18, "size": 4, "kind": "u32"},
        {"name": "checksum", "offset": 22, "size": 4, "kind": "u32"},
        {"name": "page_segments", "offset": 26, "size": 1, "kind": "u8"},
    ],
    ("1f8b", 0): [  # gzip header (RFC 1952)
        {"name": "magic", "offset": 0, "size": 2, "kind": "bytes"},
        {"name": "method", "offset": 2, "size": 1, "kind": "u8"},
        {"name": "flags", "offset": 3, "size": 1, "kind": "u8"},
        {"name": "mtime", "offset": 4, "size": 4, "kind": "u32"},
        {"name": "extra_flags", "offset": 8, "size": 1, "kind": "u8"},
        {"name": "os", "offset": 9, "size": 1, "kind": "u8"},
    ],
    ("526172211a0700", 0): [  # RAR 4.x main header
        {"name": "signature", "offset": 0, "size": 7, "kind": "bytes"},
        {"name": "header_crc", "offset": 7, "size": 2, "kind": "u16"},
        {"name": "header_type", "offset": 9, "size": 1, "kind": "u8"},
        {"name": "header_flags", "offset": 10, "size": 2, "kind": "u16"},
        {"name": "header_size", "offset": 12, "size": 2, "kind": "u16"},
    ],
    ("25504446", 0): [  # PDF header (also covers AI)
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
    ("464f524d", 0): [  # IFF FORM header (same shape as RIFF)
        {"name": "signature", "offset": 0, "size": 4, "kind": "ascii"},
        {"name": "file_size", "offset": 4, "size": 4, "kind": "u32"},
        {"name": "form_type", "offset": 8, "size": 4, "kind": "ascii"},
    ],
}

def split_blocks(text):
    parts = re.split(r'(?m)^// ===== task-(\d+) (\.\S+) \[(C\+\+|C)\] =====\s*$', text)
    blocks = {}
    for i in range(1, len(parts), 4):
        task, ext, lang, body = parts[i], parts[i + 1], parts[i + 2], parts[i + 3]
        body = re.sub(r'(?m)^// ===== end task-\d+ .*$', '', body)
        blocks.setdefault(int(task), []).append((ext, lang, body))
    return blocks

def main():
    text = open(CPP, encoding="utf-8", errors="ignore").read()
    blocks = split_blocks(text)
    formats = {}
    stats = {}
    for task in sorted(blocks):
        blist = blocks[task]
        ext = blist[0][0]
        body = blist[0][2]
        for e, l, b in blist:
            if l == "C++":
                body, ext = b, e
                break
        entry = {"task": task, "ext": ext, "name": format_name(body, ext),
                 "magic": None, "magic_off": 0,
                 "fields": [], "derivation": "unknown", "notes": ""}
        magic = find_magic(body)
        if magic:
            entry["magic"] = magic[0].hex()
            entry["magic_off"] = magic[1]
        apply_curated_magic(entry)
        entry["endian"] = detect_endian(body)
        if entry["magic"] == "3c3f786d6c" and entry["derivation"] in ("unknown", "magic-only"):
            entry["derivation"] = "text"
            entry["notes"] = "xml"
        fmap = parse_structs(body)
        fields, deriv = derive_readseq(body, fmap)
        explicit = parse_explicit(body)
        is_xml = ("tinyxml2" in body or "XMLDocument" in body or "pugixml" in body)
        is_json = ("nlohmann" in body or "Json::" in body)
        if fields:
            entry["fields"] = fields
            entry["derivation"] = deriv
        elif fmap:
            # struct present but no parseable read sequence: use struct
            # order with C-type sizes (char[N] taken as N bytes; the test
            # loop must verify — a NUL slot shifts everything by 1).
            props = [n for n, (c, a, s) in fmap.items()
                     if "ropert" in s and n not in SKIP_FIELDS]
            if not props:
                props = [n for n, (c, a, s) in fmap.items() if n not in SKIP_FIELDS]
            off = 0
            fl = []
            for name in props:
                ctype, arr, _ = fmap[name]
                kk = field_kind_size(ctype, arr)
                if not kk:
                    continue
                size, kind = kk
                fl.append({"name": name, "offset": off, "size": size, "kind": kind})
                off += size
            if len(fl) >= 2:
                entry["fields"] = fl
                entry["derivation"] = "struct"
            else:
                entry["derivation"] = "unknown"
        elif explicit:
            entry["fields"] = explicit
            entry["derivation"] = "explicit"
        elif is_xml or is_json:
            entry["derivation"] = "text"
            entry["notes"] = "xml" if is_xml else "json"
        elif magic:
            entry["derivation"] = "magic-only"
        stats[entry["derivation"]] = stats.get(entry["derivation"], 0) + 1
        formats[task] = entry

    if os.path.exists(OVERRIDES):
        ov = json.load(open(OVERRIDES))
        for k, v in ov.items():
            if not k.isdigit():
                continue
            t = int(k)
            if t in formats:
                formats[t].update(v)
                # An override may set its own derivation (e.g. "text" for a
                # text format that also needs a magic); only default to
                # "override" when it does not.
                if "derivation" not in v:
                    formats[t]["derivation"] = "override"
            else:
                # Override for a task with no code block (nocode): build a
                # complete entry from defaults, then apply the override.
                # Without this the entry lacks keys the later passes need.
                formats[t] = {"task": t, "ext": v.get("ext", ".?"),
                              "name": v.get("name", format_name("", v.get("ext", ".?"))),
                              "magic": None, "magic_off": 0, "fields": [],
                              "derivation": "override", "notes": "",
                              "endian": "le"}
                formats[t].update(v)


    # Tasks with a page but no C/C++ code block (18). They have no derived
    # layout; add them so they are identifiable by extension at least.
    # The ones that are known text/XML formats get a text kind.
    NOCODE_TEXT = {
        ".INI": ("text", None), ".M3U8": ("text", "234558544d3355"),  # #EXTM3U
        ".TWB": ("text", "3c3f786d6c"), ".VSQ": ("text", "3c3f786d6c"),
        ".DPFHTML": ("text", None),
        ".PET": ("unknown", "1f8b"),  # Puppy Linux package: gzipped tar
    }
    url_manifest = os.path.join(SCRIPT_DIR, "sample_urls.json")
    if os.path.exists(url_manifest):
        um = json.load(open(url_manifest))
        for k, v in um.items():
            t = int(k)
            if t in formats:
                continue
            ext = v.get("ext") or ".?"
            kind, magic = NOCODE_TEXT.get(ext.upper(), ("unknown", None))
            formats[t] = {"task": t, "ext": ext,
                          "name": format_name("", ext),
                          "magic": magic, "magic_off": 0,
                          "fields": [], "derivation": "nocode",
                          "notes": "no C/C++ reference code on the task page",
                          "endian": "le"}
            if kind == "text":
                formats[t]["derivation"] = "nocode-text"

    # Container-layout inheritance (second pass, AFTER overrides, so
    # override-set magics also inherit): a format with no fields that
    # shares a well-known container magic gets that container's fixed
    # header layout. Prefix match: a longer magic (e.g. ftyp3g2) still
    # belongs to its container family (ftyp).
    for t, entry in formats.items():
        if entry["fields"] or not entry["magic"]:
            continue
        inh = None
        for (cmagic, coff), layout in CONTAINER_LAYOUTS.items():
            if entry["magic_off"] == coff and entry["magic"].startswith(cmagic):
                inh = layout
                break
        if inh:
            entry["fields"] = [{k: v for k, v in f.items() if k != "be"} for f in inh]
            if entry["derivation"] != "override":
                entry["derivation"] = "container"
            if inh[0].get("be"):
                entry["endian"] = "be"

    out = {str(t): formats[t] for t in sorted(formats)}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    with_magic = sum(1 for e in formats.values() if e["magic"])
    with_fields = sum(1 for e in formats.values() if e["fields"])
    print(f"tasks: {len(formats)}")
    print(f"derivation: {stats}")
    print(f"with magic: {with_magic}  with fields: {with_fields}")
    print(f"wrote {OUT_JSON}")
    write_header(out, OUT_H)
    print(f"wrote {OUT_H}")

def c_esc(b):
    return "".join("\\x%02x" % x for x in b)

def write_header(formats, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    lines.append("/* formats.h — GENERATED by tools/gen_formats.py. Do not edit by hand;")
    lines.append("   edit tools/overrides.json and re-run the generator. */")
    lines.append("#ifndef SFILE_FORMATS_H")
    lines.append("#define SFILE_FORMATS_H")
    lines.append("")
    lines.append("typedef struct { const char *name; uint32_t offset; uint32_t size; int kind; } SField;")
    lines.append("enum { FK_U8=0, FK_U16, FK_U32, FK_U64, FK_I8, FK_I16, FK_I32, FK_I64, FK_F32, FK_F64, FK_ASCII, FK_BYTES };")
    lines.append("")
    lines.append("typedef struct { int task; const char *ext; const char *name; const char *magic; uint32_t magic_len; uint32_t magic_off; const SField *fields; int nfields; int kind; int endian; } SFormat;")
    lines.append("enum { FMT_BINARY=0, FMT_TEXT, FMT_UNKNOWN };")
    lines.append("")
    kindmap = {"u8": "FK_U8", "u16": "FK_U16", "u32": "FK_U32", "u64": "FK_U64",
               "i8": "FK_I8", "i16": "FK_I16", "i32": "FK_I32", "i64": "FK_I64",
               "f32": "FK_F32", "f64": "FK_F64", "ascii": "FK_ASCII", "bytes": "FK_BYTES"}
    for t in sorted(formats, key=lambda x: int(x)):
        e = formats[t]
        if e["fields"]:
            lines.append(f"static const SField fmt_{t}_fields[] = {{")
            for fl in e["fields"]:
                k = kindmap.get(fl["kind"], "FK_BYTES")
                nm = fl["name"].replace('"', "'")
                lines.append(f'    {{ "{nm}", {fl["offset"]}, {fl["size"]}, {k} }},')
            lines.append("};")
    lines.append("")
    lines.append("static const SFormat sfile_formats[] = {")
    for t in sorted(formats, key=lambda x: int(x)):
        e = formats[t]
        magic = bytes.fromhex(e["magic"]) if e["magic"] else b""
        fk = "FMT_TEXT" if e["derivation"] in ("text", "nocode-text") else "FMT_BINARY"
        if e["derivation"] in ("unknown", "nocode"):
            fk = "FMT_UNKNOWN"
        fields = f"fmt_{t}_fields" if e["fields"] else "NULL"
        n = len(e["fields"])
        nm = e.get("name", e["ext"]).replace('"', "'")
        en = 1 if e.get("endian") == "be" else 0
        lines.append(f'    {{ {t}, "{e["ext"]}", "{nm}", "{c_esc(magic)}", {len(magic)}, {e["magic_off"]}, {fields}, {n}, {fk}, {en} }},')
    lines.append("};")
    lines.append(f"static const int sfile_nformats = {len(formats)};")
    lines.append("#endif")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
