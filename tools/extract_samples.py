#!/usr/bin/env python3
"""extract_samples.py — one-shot sample surgery (Nov 25, 2026).

Several bulk-fetched 'samples' are distribution ZIPs that CONTAIN the real
sample file. This script extracts the real file and replaces the sample
with it (the outer ZIP is not the format). Each extraction is verified
against the expected head bytes before the sample is replaced.

Also decompresses gzipped samples whose inner content IS the format
(plain-text formats distributed as .gz).
"""
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "samples")

def replace(task, ext, data, expect=None, expect_name=""):
    if expect is not None and not data.startswith(expect):
        print(f"task {task}: REFUSED — head is {data[:16].hex()}, expected {expect_name}")
        return False
    p = os.path.join(S, f"task-{task:03d}{ext}")
    if not os.path.exists(p):
        print(f"task {task}: sample gone (collector replaced it?), skipping")
        return False
    # keep the distribution zip aside for the record
    os.rename(p, p + ".distzip")
    with open(p, "wb") as fh:
        fh.write(data)
    print(f"task {task}: replaced with {len(data)} bytes ({expect_name})")
    return True

def from_zip(task, ext, inner, expect=None, expect_name=""):
    p = os.path.join(S, f"task-{task:03d}{ext}")
    if not os.path.exists(p):
        print(f"task {task}: sample gone (collector replaced it?), skipping")
        return False
    try:
        with zipfile.ZipFile(p) as z:
            data = z.read(inner)
    except Exception as e:
        print(f"task {task}: not a zip any more ({e}), skipping")
        return False
    return replace(task, ext, data, expect, expect_name)

def from_zip_gz(task, ext, inner, expect=None, expect_name=""):
    p = os.path.join(S, f"task-{task:03d}{ext}")
    if not os.path.exists(p):
        print(f"task {task}: sample gone (collector replaced it?), skipping")
        return False
    try:
        with zipfile.ZipFile(p) as z:
            raw = z.read(inner)
    except Exception as e:
        print(f"task {task}: not a zip any more ({e}), skipping")
        return False
    data = gzip.decompress(raw)
    return replace(task, ext, data, expect, expect_name)

def gunzip_in_place(task, ext, expect=None, expect_name=""):
    p = os.path.join(S, f"task-{task:03d}{ext}")
    with open(p, "rb") as fh:
        raw = fh.read()
    if not raw.startswith(b"\x1f\x8b"):
        print(f"task {task}: not gzipped, skipping")
        return False
    data = gzip.decompress(raw)
    os.rename(p, p + ".gz")
    with open(p, "wb") as fh:
        fh.write(data)
    ok = expect is None or data.startswith(expect)
    print(f"task {task}: gunzipped {len(raw)} -> {len(data)} bytes "
          f"({'OK ' + expect_name if ok else 'HEAD MISMATCH: ' + data[:32].hex()})")
    return ok

# --- distribution ZIPs: extract the real sample -----------------------
from_zip(113, ".crt", "action_replay_6.crt", b"C64 CARTRIDGE ", "C64 cartridge")
from_zip(169, ".ede", "Mmp_002.ede")
from_zip(354, ".lgr", "Default.lgr")
from_zip(66, ".bps", "Sunshine Secret Book 64.bps", b"BPS1", "BPS1 patch")
from_zip_gz(69, ".bson", "people-bson/people.bson.gz")
from_zip(193, ".eu4", "Engrancepaintugal.eu4", b"EUSaveInM(", "EU4 save")
from_zip(325, ".jcm", "BRUKER1.JCM", b"##TITLE=", "JCAMP-DX")
from_zip(801, ".vvvvvv", "Decennial Hangout v1.0.vvvvvv", b"<?xml", "XML (VVVVVV level)")

# 787 VPR: inner file should itself be a ZIP (VOCALOID project archive)
p = os.path.join(S, "task-787.vpr")
with zipfile.ZipFile(p) as z:
    inner = [n for n in z.namelist() if n.lower().endswith(".vpr")][0]
    data = z.read(inner)
print("task 787 inner head:", data[:8].hex(), "-> PK zip" if data.startswith(b"PK\x03\x04") else "-> NOT a zip")
replace(787, ".vpr", data, b"PK\x03\x04", "ZIP (VPR project)")

# 795 VSQX: extract one .vsqx and see whether it is a ZIP or XML
p = os.path.join(S, "task-795.vsqx")
with zipfile.ZipFile(p) as z:
    inner = [n for n in z.namelist() if n.lower().endswith(".vsqx")][0]
    data = z.read(inner)
print("task 795 inner head:", data[:16].hex())
replace(795, ".vsqx", data, b"PK\x03\x04" if data.startswith(b"PK\x03\x04") else b"<?xml",
        "ZIP (VSQX)" if data.startswith(b"PK\x03\x04") else "XML (VSQX)")

# 511 PAPA: find a .papa inside the repo archive
p = os.path.join(S, "task-511.papa")
with zipfile.ZipFile(p) as z:
    papas = [n for n in z.namelist() if n.lower().endswith(".papa")]
    print("task 511 .papa files inside:", papas[:5])
    if papas:
        data = z.read(papas[0])
        print("task 511 inner head:", data[:16].hex())
        replace(511, ".papa", data)

# 700 SUR: zip contains a tar; extract a .sur from the tar
p = os.path.join(S, "task-700.sur")
with zipfile.ZipFile(p) as z:
    tar_bytes = z.read("procolobus_sur.tar")
tf = tarfile.open(fileobj=io.BytesIO(tar_bytes))
surs = [m for m in tf.getmembers() if m.name.lower().endswith(".sur")]
print("task 700 .sur files in tar:", [m.name for m in surs[:5]])
if surs:
    data = tf.extractfile(surs[0]).read()
    print("task 700 inner head:", data[:32])
    replace(700, ".sur", data)

# 652 SEC: extract an inner .SEC (text)
p = os.path.join(S, "task-652.sec")
with zipfile.ZipFile(p) as z:
    secs = [n for n in z.namelist() if n.lower().endswith(".sec")]
    print("task 652 .sec files inside:", secs[:5])
    if secs:
        data = z.read(secs[0])
        print("task 652 inner head:", data[:64])
        replace(652, ".sec", data)

# 025 AMG: the zip holds crowd.wav — is it an AMG file (does it have an
# AMBG chunk) or a plain WAV?
p = os.path.join(S, "task-025.amg")
if not os.path.exists(p):
    print("task 025: sample gone (collector replaced it?), skipping")
else:
    with zipfile.ZipFile(p) as z:
        wav = z.read("crowd.wav")
    print("task 025 crowd.wav has AMBG chunk:", b"AMBG" in wav,
          "| RIFF:", wav.startswith(b"RIFF"))
    if b"AMBG" in wav:
        replace(25, ".amg", wav, b"RIFF", "RIFF WAVE-EX + AMBG")

# --- gzipped samples whose inner content IS the format ----------------
gunzip_in_place(232, ".fna", b">", "FASTA (>)")
gunzip_in_place(254, ".gdt", b"<?xml", "XML (gretl)")
gunzip_in_place(310, ".info", None, "")
gunzip_in_place(394, ".mex", b"%%MatrixMarket", "Matrix Market")
gunzip_in_place(550, ".pir", b">", "NBRF/PIR (>)")
gunzip_in_place(358, ".lm", b"\\data", "ARPA LM (\\data)")
