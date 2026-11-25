#!/usr/bin/env python3
"""extract_cpp.py — extract ONLY the C/C++ code blocks from the downloaded
fileformat.vpscoder.com task pages into a single combined file.

Each task page has numbered sections (Python, Java, JavaScript, C/C++).
The section intro immediately before a code block names its language
(the intro can be an <h3>, a <p><strong>, a bare <li>, or a plain <p> —
the text window before the block catches all of them). This script
classifies each code block by that intro text and keeps only the C/C++
ones — never Python, Java, JavaScript, or HTML. The [C] vs [C++] tag
comes from the code itself (C has no `class` keyword; C++ does).

Output is a single C++ file, one clearly delimited block per format:
    // ===== task-845 .XSL [C++] =====
    ...code...
    // ===== end task-845 .XSL =====

Usage:
    ./extract_cpp.py [pages_dir] [output_file]
    pages_dir defaults to "pages/" next to this script.
    output_file defaults to "all_formats.cpp" next to this script.

Prints a summary: pages processed, tasks with C++ saved, tasks with C
saved, tasks with no C/C++ section, tasks with an empty code block.
"""

import hashlib
import html
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "pages")
OUT_FILE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRIPT_DIR, "all_formats.cpp")

CODE_RE = re.compile(r"<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>", re.S | re.I)
TITLE_RE = re.compile(r"Task\s+(\d+)\s*[:\-]?\s*\.?([A-Za-z0-9]+)", re.I)


def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text).strip()


def code_lang(code):
    """Classify a C/C++ code block by its content (ground truth for the
    [C] vs [C++] marker). C has no `class` keyword; C++ does, and uses
    C++-only headers / std::."""
    if re.search(r"\bclass\b", code):
        return "cpp"
    if re.search(r"#include\s*<(iostream|fstream|sstream|string|vector|map|set|algorithm|memory|utility|cstdint|cstring|ctime|iomanip|functional)>", code):
        return "cpp"
    if "std::" in code:
        return "cpp"
    if re.search(r"#include\s*<stdio\.h>", code) or re.search(r"\bstruct\s+\w+", code):
        return "c"
    return None


INTRO_RE = re.compile(
    r"(?P<cpp>C\+\+)|(?P<js>JavaScript)|(?P<py>Python)|(?P<java>\bJava\b)"
    r"|(?P<c>\bC\s+\"?(?:class|implementation|struct)\b)",
    re.I,
)


def classify_intro(text):
    """Language of the section intro immediately before a code block:
    the LAST language indicator in the text (closest to the block).
    Returns 'cpp', 'c', 'python', 'java', 'js', or None."""
    last = None
    for m in INTRO_RE.finditer(text):
        lang = next(k for k, v in m.groupdict().items() if v is not None)
        last = (m.start(), lang)
    return last[1] if last else None


def extract_task(path):
    """Return (task_id, ext, cpp_code_or_None, c_code_or_None, note)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        page = f.read()

    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    title = strip_tags(m.group(1)) if m else ""
    tm = TITLE_RE.search(title)
    task_id = tm.group(1) if tm else None
    ext = tm.group(2) if tm else None

    # Classify each code block by the text immediately before it (the
    # section intro). Section headings/intros appear as <h3>, <p><strong>,
    # <li>, or a plain <p> — the intro window catches all of them.
    # The window is the text since the previous code block ended, so it
    # holds only this section's intro; the LAST language indicator in it
    # (closest to the block) is the section's language.
    code_matches = list(CODE_RE.finditer(page))
    cpp_blocks, c_blocks = [], []
    prev_end = 0
    for i, mm in enumerate(code_matches):
        code = html.unescape(mm.group(1))
        window = page[prev_end:mm.start()]
        text = re.sub(r"<[^>]+>", " ", window)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        lang = classify_intro(text)
        if lang is None and i == len(code_matches) - 1:
            # Fallback: the C/C++ section is always last. If its intro
            # says nothing, trust the code itself — but only on a hard
            # C/C++ signal (#include), so a JavaScript last block is
            # never mistaken for C/C++.
            if re.search(r"#include\s*<", code):
                lang = code_lang(code) or "cpp"
        if lang in ("cpp", "c"):
            # The code itself decides [C] vs [C++] (headings sometimes
            # say "C class" for code implemented as a C++ class).
            final = code_lang(code) or lang
            if final == "cpp":
                cpp_blocks.append(code)
            else:
                c_blocks.append(code)
        prev_end = mm.end()

    if task_id is None:
        # Fall back to the filename task-NNN.html
        base = os.path.basename(path)
        fm = re.match(r"task-(\d+)\.html$", base)
        task_id = fm.group(1) if fm else "?"

    ext = (ext or "?").strip()
    cpp = "\n\n".join(b.strip("\n") for b in cpp_blocks if b.strip()) or None
    c = "\n\n".join(b.strip("\n") for b in c_blocks if b.strip()) or None
    note = ""
    if not cpp and not c:
        note = "no C/C++ section" if not (cpp_blocks or c_blocks) else "empty C/C++ code block"
    return task_id, ext, cpp, c, note


def file_sort_key(path):
    """Sort by task number, then filename (so task-2 and task-002 sort together)."""
    base = os.path.basename(path)
    m = re.search(r"task-0*(\d+)", base)
    num = int(m.group(1)) if m else 10**9
    return (num, base)


def main():
    files = sorted(
        (os.path.join(PAGES_DIR, fn) for fn in os.listdir(PAGES_DIR)
         if re.match(r"task-.*\.html$", fn)),
        key=file_sort_key,
    )
    n_pages = n_cpp = n_c = n_none = n_empty = n_dup = 0
    no_cpp_tasks, empty_tasks = [], []
    seen = set()  # (task_id, ext, lang, sha256(code)) — skip exact duplicates
    out_lines = [
        "// all_formats.cpp — C/C++ handler classes for the file formats at",
        "// fileformat.vpscoder.com, extracted from the task pages.",
        "// Each format is delimited by a marker comment:",
        "//   // ===== task-NNN .EXT [C++] =====   (or [C] for a C section)",
        "// so the file is greppable per format, e.g. grep -n 'task-845'.",
        "// Generated by extract_cpp.py from the raw pages in pages/.",
        "// The Python / Java / JavaScript / HTML sections were NOT included.",
        "// Some task numbers have more than one post (e.g. /task-002/ and",
        "// /task-2/); identical code appearing twice was kept only once.",
        "",
    ]
    for path in files:
        n_pages += 1
        task_id, ext, cpp, c, note = extract_task(path)
        marker_ext = ("." + ext) if not ext.startswith(".") and ext != "?" else ext
        if cpp:
            key = (task_id, ext, "C++", hashlib.sha256(cpp.encode()).hexdigest())
            if key in seen:
                n_dup += 1
            else:
                seen.add(key)
                n_cpp += 1
                out_lines.append(f"// ===== task-{task_id} {marker_ext} [C++] =====")
                out_lines.append(cpp)
                out_lines.append(f"// ===== end task-{task_id} {marker_ext} =====")
                out_lines.append("")
        if c:
            key = (task_id, ext, "C", hashlib.sha256(c.encode()).hexdigest())
            if key in seen:
                n_dup += 1
            else:
                seen.add(key)
                n_c += 1
                out_lines.append(f"// ===== task-{task_id} {marker_ext} [C] =====")
                out_lines.append(c)
                out_lines.append(f"// ===== end task-{task_id} {marker_ext} =====")
                out_lines.append("")
        if not cpp and not c:
            n_none += 1
            no_cpp_tasks.append(task_id)
            if "empty" in note:
                n_empty += 1
                empty_tasks.append(task_id)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    total_lines = sum(1 for _ in open(OUT_FILE, encoding="utf-8"))
    total_bytes = os.path.getsize(OUT_FILE)
    print(f"pages processed: {n_pages}")
    print(f"tasks with C++ saved: {n_cpp}")
    print(f"tasks with C saved: {n_c}")
    print(f"duplicate code blocks skipped: {n_dup}")
    print(f"tasks with no C/C++ section or empty block: {n_none} (of which empty block: {n_empty})")
    print(f"output: {OUT_FILE} — {total_lines} lines, {total_bytes} bytes")
    if no_cpp_tasks:
        print(f"no C/C++ tasks: {', '.join(no_cpp_tasks)}")
    if empty_tasks:
        print(f"empty C/C++ block tasks: {', '.join(empty_tasks)}")


if __name__ == "__main__":
    main()
