#!/usr/bin/env python3
"""apply_testloop_overrides8.py — eighth batch (Nov 25, 2026 test loop).
Hand-written layouts for 20 prominent binary formats, verified against
their real samples (ar/DEB, DICOM, EPS, EXR, HDF5, ELF, TGA, S3M, IT,
3DS, FBX, MOBI, NetCDF, AU, DPX, CHM, RealMedia, DWF, torrent-as-text),
plus the MZ/DOS container layout and three bogus MZ magics removed.
Run: python3 tools/apply_testloop_overrides8.py  (then: make table)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ov = json.load(open(os.path.join(HERE, "overrides.json")))

def F(name, off, size, kind):
    return {"name": name, "offset": off, "size": size, "kind": kind}

NEW = {
    # ar archive (Debian .deb is an ar archive; first member is debian-binary)
    "134": {"magic": "213c617263683e0a",
            "fields": [F("signature", 0, 8, "ascii"),
                       F("first_member_name", 8, 16, "ascii"),
                       F("first_member_mtime", 24, 12, "ascii"),
                       F("first_member_uid", 36, 6, "ascii"),
                       F("first_member_gid", 42, 6, "ascii"),
                       F("first_member_mode", 48, 8, "ascii"),
                       F("first_member_size", 56, 10, "ascii"),
                       F("first_member_magic", 66, 2, "ascii")],
            "derivation": "override",
            "notes": "ar archive header + first member header; sample's first member is debian-binary"},
    # DICOM: 128-byte preamble then 'DICM' at offset 128
    "137": {"magic": "4449434d", "magic_off": 128,
            "fields": [F("preamble", 0, 128, "bytes"),
                       F("dicom_magic", 128, 4, "ascii")],
            "derivation": "override",
            "notes": "DICOM preamble (128 bytes, usually zero) + DICM magic at 128; data elements after that are TLV, no fixed layout"},
    # Adobe EPS binary header (EPSF spec)
    "184": {"fields": [F("magic", 0, 4, "bytes"),
                       F("ps_start", 4, 4, "u32"),
                       F("ps_length", 8, 4, "u32"),
                       F("metafile_start", 12, 4, "u32"),
                       F("metafile_length", 16, 4, "u32"),
                       F("tiff_start", 20, 4, "u32"),
                       F("tiff_length", 24, 4, "u32"),
                       F("checksum", 28, 2, "u16")],
            "derivation": "override",
            "notes": "Adobe EPS binary header (EPSF); sample has a TIFF preview at offset 30"},
    # OpenEXR: magic 0x01312F76 (LE) + version
    "199": {"magic": "762f3101",
            "fields": [F("magic", 0, 4, "bytes"),
                       F("version", 4, 4, "u32")],
            "derivation": "override",
            "notes": "OpenEXR header; attributes after the version are TLV, no fixed layout"},
    # HDF5 superblock version 0 (this sample)
    "283": {"magic": "894844460d0a1a0a",
            "fields": [F("signature", 0, 8, "bytes"),
                       F("superblock_version", 8, 1, "u8"),
                       F("freespace_storage_version", 9, 1, "u8"),
                       F("root_group_symbol_table_entry_version", 10, 1, "u8"),
                       F("reserved", 11, 1, "u8"),
                       F("shared_header_message_version", 12, 1, "u8"),
                       F("size_of_offsets", 13, 1, "u8"),
                       F("size_of_lengths", 14, 1, "u8"),
                       F("reserved2", 15, 1, "u8"),
                       F("group_leaf_node_k", 16, 2, "u16"),
                       F("group_internal_node_k", 18, 2, "u16"),
                       F("file_consistency_flags", 20, 4, "u32"),
                       F("base_address", 24, 8, "u64"),
                       F("address_of_file_free_space_info", 32, 8, "u64"),
                       F("end_of_file_address", 40, 8, "u64"),
                       F("driver_information_block_address", 48, 8, "u64")],
            "derivation": "override",
            "notes": "HDF5 superblock v0 (address fields assume size_of_offsets=8, as in this sample); v2/v3 superblocks differ"},
    # ELF 64-bit header (this sample is ELF64, little-endian)
    "467": {"fields": [F("e_ident", 0, 16, "bytes"),
                       F("e_type", 16, 2, "u16"),
                       F("e_machine", 18, 2, "u16"),
                       F("e_version", 20, 4, "u32"),
                       F("e_entry", 24, 8, "u64"),
                       F("e_phoff", 32, 8, "u64"),
                       F("e_shoff", 40, 8, "u64"),
                       F("e_flags", 48, 4, "u32"),
                       F("e_ehsize", 52, 2, "u16"),
                       F("e_phentsize", 54, 2, "u16"),
                       F("e_phnum", 56, 2, "u16"),
                       F("e_shentsize", 58, 2, "u16"),
                       F("e_shnum", 60, 2, "u16"),
                       F("e_shstrndx", 62, 2, "u16")],
            "derivation": "override",
            "notes": "ELF 64-bit header; 32-bit files have a different layout after e_version"},
    # TGA header (18 bytes)
    "725": {"fields": [F("id_length", 0, 1, "u8"),
                       F("color_map_type", 1, 1, "u8"),
                       F("image_type", 2, 1, "u8"),
                       F("color_map_origin", 3, 2, "u16"),
                       F("color_map_length", 5, 2, "u16"),
                       F("color_map_depth", 7, 1, "u8"),
                       F("x_origin", 8, 2, "u16"),
                       F("y_origin", 10, 2, "u16"),
                       F("width", 12, 2, "u16"),
                       F("height", 14, 2, "u16"),
                       F("pixel_depth", 16, 1, "u8"),
                       F("image_descriptor", 17, 1, "u8")],
            "derivation": "override",
            "notes": "TGA header; sample is 640x426, 24-bit, type 2 (uncompressed true-color)"},
    # S3M: song name, 0x1A EOF marker, type 0x10, reserved, then counts; SCRM at 44
    "631": {"magic": "5343524d", "magic_off": 44,
            "fields": [F("songname", 0, 28, "ascii"),
                       F("eof_marker", 28, 1, "u8"),
                       F("type", 29, 1, "u8"),
                       F("reserved", 30, 2, "u16"),
                       F("ordnum", 32, 2, "u16"),
                       F("insnum", 34, 2, "u16"),
                       F("patnum", 36, 2, "u16"),
                       F("flags", 38, 2, "u16"),
                       F("cwtv", 40, 2, "u16"),
                       F("ffv", 42, 2, "u16"),
                       F("magic", 44, 4, "ascii"),
                       F("global_volume", 48, 1, "u8"),
                       F("initial_speed", 49, 1, "u8"),
                       F("initial_tempo", 50, 1, "u8"),
                       F("master_volume", 51, 1, "u8")],
            "derivation": "override",
            "notes": "ScreamTracker 3 module header; sample: 30 orders, 22 instruments, 24 patterns"},
    # Impulse Tracker module
    "318": {"magic": "494d504d",
            "fields": [F("magic", 0, 4, "ascii"),
                       F("songname", 4, 26, "ascii"),
                       F("reserved", 30, 2, "u16"),
                       F("ordnum", 32, 2, "u16"),
                       F("insnum", 34, 2, "u16"),
                       F("smpnum", 36, 2, "u16"),
                       F("patnum", 38, 2, "u16"),
                       F("cwtv", 40, 2, "u16"),
                       F("cmwt", 42, 2, "u16"),
                       F("flags", 44, 2, "u16"),
                       F("special", 46, 2, "u16")],
            "derivation": "override",
            "notes": "Impulse Tracker module header; sample: 61 orders, 10 instruments, 18 samples, 53 patterns"},
    # 3DS: chunk-based; main chunk 0x4D4D + length
    "1": {"magic": "4d4d",
          "fields": [F("chunk_id", 0, 2, "u16"),
                     F("chunk_length", 2, 4, "u32")],
          "derivation": "override",
          "notes": "3DS main chunk (0x4D4D); sub-chunks follow, no fixed file header. The 2-byte magic is shorter than TIFF-BE's 4-byte MM magic, so TIFF files still win"},
    # FBX binary: 'Kaydara FBX Binary  \\0' + version u32 at 23
    "218": {"magic": "4b617964617261204642582042696e617279202000",
            "fields": [F("magic", 0, 21, "ascii"),
                       F("version", 23, 4, "u32")],
            "derivation": "override",
            "notes": "FBX binary header; sample version 7400 (FBX 2016)"},
    # MOBI = Palm database; 'BOOK' type and 'MOBI' creator at 60/64
    "405": {"magic": "4d4f4249", "magic_off": 64, "endian": "be",
            "fields": [F("name", 0, 32, "ascii"),
                       F("attributes", 32, 2, "u16"),
                       F("version", 34, 2, "u16"),
                       F("creation_time", 36, 4, "u32"),
                       F("modification_time", 40, 4, "u32"),
                       F("backup_time", 44, 4, "u32"),
                       F("modification_number", 48, 4, "u32"),
                       F("app_info_id", 52, 4, "u32"),
                       F("sort_info_id", 56, 4, "u32"),
                       F("type", 60, 4, "ascii"),
                       F("creator", 64, 4, "ascii"),
                       F("unique_id_seed", 68, 4, "u32"),
                       F("next_record_list_id", 72, 4, "u32"),
                       F("num_records", 76, 2, "u16")],
            "derivation": "override",
            "notes": "MOBI (Palm database header, big-endian); sample has 397 records"},
    # NetCDF classic: 'CDF' + version + numrecs (big-endian)
    "441": {"magic": "434446", "endian": "be",
            "fields": [F("magic", 0, 3, "ascii"),
                       F("version", 3, 1, "u8"),
                       F("numrecs", 4, 4, "u32")],
            "derivation": "override",
            "notes": "NetCDF classic header (version 1 = CDF\\x01); dimensions/attributes/variables after numrecs are variable"},
    # Sun Audio (.snd), big-endian
    "46": {"magic": "2e736e64", "endian": "be",
           "fields": [F("magic", 0, 4, "ascii"),
                      F("offset", 4, 4, "u32"),
                      F("data_size", 8, 4, "u32"),
                      F("encoding", 12, 4, "u32"),
                      F("sample_rate", 16, 4, "u32"),
                      F("channels", 20, 4, "u32")],
           "derivation": "override",
           "notes": "Sun Audio header; sample: 44100 Hz, 2 channels, encoding 3 (16-bit linear PCM)"},
    # DPX (SMPTE 268M), big-endian ('SDPX')
    "152": {"magic": "53445058", "endian": "be",
            "fields": [F("magic", 0, 4, "ascii"),
                       F("offset_to_image_data", 4, 4, "u32"),
                       F("version", 8, 8, "ascii"),
                       F("file_size", 16, 4, "u32"),
                       F("ditto_key", 20, 4, "u32"),
                       F("generic_header_length", 24, 4, "u32"),
                       F("industry_header_length", 28, 4, "u32"),
                       F("user_header_length", 32, 4, "u32"),
                       F("file_name", 36, 100, "ascii")],
            "derivation": "override",
            "notes": "DPX file header (big-endian SDPX); sample is V1.0, image data at offset 2048"},
    # CHM: ITSF header
    "86": {"fields": [F("signature", 0, 4, "ascii"),
                      F("version", 4, 4, "u32"),
                      F("header_size", 8, 4, "u32"),
                      F("unknown", 12, 4, "u32"),
                      F("timestamp", 16, 4, "u32"),
                      F("language", 20, 4, "u32"),
                      F("guid", 24, 16, "bytes")],
           "derivation": "override",
           "notes": "CHM ITSF header; sample version 3, header size 0x60"},
    # RealMedia file header (.RMF), big-endian
    "614": {"magic": "2e524d46", "endian": "be",
            "fields": [F("signature", 0, 4, "ascii"),
                       F("size", 4, 4, "u32"),
                       F("object_version", 8, 2, "u16"),
                       F("file_version", 10, 4, "u32"),
                       F("num_headers", 14, 4, "u32")],
            "derivation": "override",
            "notes": "RealMedia file header (.RMF); sample has 6 headers"},
    "616": {"magic": "2e524d46", "endian": "be",
            "fields": [F("signature", 0, 4, "ascii"),
                       F("size", 4, 4, "u32"),
                       F("object_version", 8, 2, "u16"),
                       F("file_version", 10, 4, "u32"),
                       F("num_headers", 14, 4, "u32")],
            "derivation": "override",
            "notes": "RealMedia file header (.RMF); sample has 6 headers"},
    # DWF: '(DWF Vxx.xx)' text header
    "158": {"magic": "2844574620",
            "fields": [F("header", 0, 12, "ascii")],
            "derivation": "override",
            "notes": "DWF text header; sample is V00.24; the body after the header is binary"},
    # torrent files are bencode (ASCII)
    "734": {"fields": [], "derivation": "text",
            "notes": "torrent files are bencode (ASCII text)"},
    # Bogus MZ magics: these samples are not MZ executables.
    "101": {"magic": None,
            "notes": "the .com sample is raw x86 code, not an MZ executable; the code-derived MZ magic was wrong"},
    "645": {"magic": None,
            "notes": "the .scr sample starts with zeros, not MZ; the code-derived MZ magic was wrong"},
    "106": {"magic": None,
            "notes": "the .cpl sample is a CSV pick-and-place list, not a Windows PE; the code-derived MZ magic was wrong"},
}
for k, v in NEW.items():
    ov[k] = v
with open(os.path.join(HERE, "overrides.json"), "w") as f:
    json.dump(ov, f, indent=1, sort_keys=True)

# --- MZ/DOS container layout + text guard in the generator ---
p = os.path.join(HERE, "gen_formats.py")
s = open(p).read()
mz = '''    ("4d5a", 0): [  # DOS MZ executable header (also .EXE/.AX/.OCX/.SFX/...)
        {"name": "signature", "offset": 0, "size": 2, "kind": "ascii"},
        {"name": "bytes_last_page", "offset": 2, "size": 2, "kind": "u16"},
        {"name": "pages", "offset": 4, "size": 2, "kind": "u16"},
        {"name": "relocations", "offset": 6, "size": 2, "kind": "u16"},
        {"name": "header_size", "offset": 8, "size": 2, "kind": "u16"},
        {"name": "min_alloc", "offset": 10, "size": 2, "kind": "u16"},
        {"name": "max_alloc", "offset": 12, "size": 2, "kind": "u16"},
        {"name": "ss", "offset": 14, "size": 2, "kind": "u16"},
        {"name": "sp", "offset": 16, "size": 2, "kind": "u16"},
        {"name": "checksum", "offset": 18, "size": 2, "kind": "u16"},
        {"name": "ip", "offset": 20, "size": 2, "kind": "u16"},
        {"name": "cs", "offset": 22, "size": 2, "kind": "u16"},
        {"name": "reloc_table_offset", "offset": 24, "size": 2, "kind": "u16"},
        {"name": "overlay", "offset": 26, "size": 2, "kind": "u16"},
        {"name": "oem_id", "offset": 36, "size": 2, "kind": "u16"},
        {"name": "oem_info", "offset": 38, "size": 2, "kind": "u16"},
        {"name": "pe_header_offset", "offset": 60, "size": 4, "kind": "u32"},
    ],
'''
anchor = '    ("464f524d", 0): [  # IFF FORM header (same shape as RIFF)'
assert anchor in s
s = s.replace(anchor, mz + anchor)
# Text formats must never inherit a binary container layout.
old = '''    for t, entry in formats.items():
        if entry["fields"] or not entry["magic"]:
            continue'''
new = '''    for t, entry in formats.items():
        if entry["fields"] or not entry["magic"]:
            continue
        # Text formats never inherit a binary container layout: a text
        # format can share a magic with a binary container (e.g. a .cpl
        # that is a CSV pick-and-place list, not a PE).
        if entry["derivation"] in ("text", "nocode-text"):
            continue'''
assert old in s
s = s.replace(old, new)
open(p, "w").write(s)
print(f"batch 8 applied: {len(NEW)} overrides + MZ container layout + text guard")
