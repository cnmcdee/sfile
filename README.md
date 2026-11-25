# sfile — super file

`sfile` is a `file` command that does **detailed file header decoding**.
Given a file, it identifies the format (by magic bytes, falling back to the
filename extension) and prints the header as a uniform table: field names,
offsets, sizes and values.

```
$ sfile photo.png
File: photo.png (15234 bytes)
Format: PNG image (.PNG) — task 564
Identified by: magic
Magic: 89 50 4e 47 0d 0a 1a 0a at offset 0
Header (big-endian):
  offset   size   field                        value
  0        8      signature                    89 50 4e 47 0d 0a 1a 0a
  8        4      ihdr_length                  13
  12       4      ihdr_type                    "IHDR"
  16       4      width                        800
  20       4      height                       600
  24       1      bit_depth                    8
  25       1      color_type                   2
  ...
```

## Coverage

831 formats (the 849 that exist at fileformat.vpscoder.com — "860" is the
max task number; 11 numbers have no published page). The format table is
derived from the C/C++ reference code for each format (see
`tools/all_formats.cpp`, 833 code blocks from 831 tasks) plus a curated
magic table and hand overrides for well-known container formats
(PNG, ZIP, WAV/AVI, GIF, BMP, tar, …).

| derivation | count | meaning |
|---|---|---|
| `readseq` | 30 | fields + offsets from a parsed sequential read sequence (highest confidence) |
| `struct` | 210 | struct fields in order, sizes from C types (char[N] NUL slots are a known risk — the test loop verifies) |
| `explicit` | 3 | C++ class reading `data[N]` / `data + N` with named properties |
| `text` | 220 | XML/JSON/text format — decoded by the text decoder (root element, version, first line) |
| `container` | 65 | inherits a container's fixed header (ZIP local header, RIFF, ftyp, Ogg page, gzip, RAR 4.x, IFF FORM, PDF, TIFF, OLE/CFB) |
| `override` | 78 | hand-written, spec-derived layout — verified against real samples |
| `magic-only` | 4 | magic known, no fixed field layout |
| `nocode` | 10 | no C/C++ code on the task page, no layout derived |
| `nocode-text` | 5 | no C/C++ code, but the format is text |
| `unknown` | 224 | nothing derivable from the reference code — identified by magic/extension only, hex dump shown |

292 formats have a magic signature; 385 have a field layout. The 18 tasks
with no C/C++ code at all (108, 151, 172, 233, 300, 312, 345, 369, 398, 408,
532, 623, 671, 720, 741, 757, 793, 794) are `nocode`/`nocode-text` unless a
hand override exists for them (300 ICE and 398 MKA have overrides).

## Testing

`tests/run_tests.py` runs `sfile` on every sample in `samples/` (one real
sample file per format, collected from the task pages' download links or by
web search) and records PASS / PARTIAL / FAIL / NO SAMPLE in
`tests/results.json`. Latest run (Nov 25, 2026):

| result | count | meaning |
|---|---|---|
| PASS | 440 | identified and header decoded |
| PARTIAL | 82 | identified, no derivable layout (mostly binary formats whose reference code is chunk-scanning or variable-length; EBML formats; a few honest no-layout cases) |
| FAIL | 2 | 312 (.INI) and 520 (.PBO) — both are duplicate tasks (311 and 519 describe the same format); indistinguishable by content |
| NO SAMPLE | 325 | no real sample file found yet (sample collection in progress) |

Fixes from the test loop live in `tools/apply_testloop_overrides*.py`
(six batches so far, 247 overrides total): bogus magics removed
(`##`, `##TITLE=` for the wrong format, `xmlns:`, `504b0506` as a file
magic, …), wrong extensions fixed (.JVX→.JXL, .files→.MKA, .LGA→.LHA,
.files→.ICE, .OTS→.OTT, .OSB→.OSC), container layouts added, and ~130
formats verified as text from their samples and pages. Wrong samples
(404 pages, HTML error pages, distribution archives, PDFs mislabeled as
other formats, JS libraries saved as samples) are deleted, not tested.

## Design

**Table-driven, generic engine.** All per-format knowledge lives in the
generated table `src/formats.h` (one entry per format: extension, name,
magic bytes + offset, field list of name/offset/size/kind, endianness).
The engine (`src/sfile.c`) contains no per-format decode logic — it walks
the table, matches magic, and formats the fields. A format is never
"guessed": the decode is derived from the collected reference code, a
published format spec (the hand overrides), or a verified sample file,
and the derivation is recorded per format in `src/formats.json`.

**Identification order.** Longest magic match wins. Several formats share
a magic (all ZIP-based formats share `PK\x03\x04`; all RIFF formats share
`RIFF`); when that happens the filename extension disambiguates and the
other candidates are listed. If no magic matches, the extension is used.
If neither matches, sfile reports "unknown" with a hex dump.

**Endianness.** Per-format, detected from the reference code (use of
`ntohl`/`ntohs`/big-endian readers) or from the spec (PNG, TIFF, Java
class files are big-endian). Default is little-endian.

**Text formats.** XML files decode to document type + root element +
version attribute; JSON to document type + first key; plain text to the
first line.

## Building

```
make            # builds ./sfile (gcc, -O2 -Wall -Wextra, no exotic deps)
make table      # regenerate src/formats.h from tools/all_formats.cpp
make test       # run the per-format test loop over samples/
make install    # install to /usr/local/bin (PREFIX=... to change)
```

## Usage

```
sfile <file>        identify + decode the header
sfile --list        list all known formats (task, extension, name)
sfile --help
```

Exit codes: 0 identified, 1 usage error, 2 file unreadable, 3 unknown format.

## Testing

`tests/run_tests.py` runs sfile over every sample in `samples/` and
records, per format, whether it was identified correctly and whether a
header decode was produced:

- **PASS** — identified correctly AND a decode was produced.
- **PARTIAL** — identified, but no header layout exists yet (needs a hand
  override or a sample-derived layout).
- **FAIL** — misidentified or unknown.
- **NO SAMPLE** — no sample file could be found for that format.

Sample files come from the task pages' "Direct Download Links" first
(`tools/sample_urls.json`, 1,726 URLs across 849 tasks); where those links
are dead or missing, samples were found by searching the web. Each sample
is recorded in `samples/manifest-*.json` with its source URL and SHA-256.

The test loop is the ground truth for the table: a field layout that
decodes a real sample wrongly (wrong magic, fields past EOF, implausible
values) is fixed in `tools/overrides.json` and the table regenerated.
`tests/results.json` holds the latest per-format results.

## Layout

```
sfile/
  src/sfile.c           the engine (generic; no per-format code)
  src/formats.h         generated format table (do not edit by hand)
  src/formats.json      the table as JSON (source of truth for tests)
  tools/gen_formats.py  generator: reference code -> formats.json/.h
  tools/all_formats.cpp the collected C/C++ reference code (833 blocks)
  tools/overrides.json  hand overrides (spec-derived layouts, magic fixes)
  tools/sample_urls.json download links per task (from the task pages)
  tools/get_sample_urls.py  extracts sample_urls.json from the raw pages
  tools/extract_cpp.py  extracts all_formats.cpp from the raw pages
  tests/run_tests.py    the per-format test loop
  tests/results.json    latest test results
  samples/              one real sample file per format + manifests
```

## Sources

Format reference code: https://fileformat.vpscoder.com (849 task pages).
The C/C++ code there is the reference for each format's header structure;
`sfile`'s table is derived from it, verified against real sample files,
and corrected where the reference code is wrong (the reference code is
AI-generated and is not always a correct spec — the test loop is what
catches that).

## License

MIT, copyright 2026 cnmcdee.
