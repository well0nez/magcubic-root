#!/usr/bin/env python3
"""
awimg.py - Allwinner IMAGEWTY firmware image tool
Supports PhoenixSuit/PhoenixUSBPro .img format (v1, v3, and newer variants).

Commands:
  list    <image.img>                              - list all files
  extract <image.img> <output_dir/>                - extract all files
  replace <image.img> <filename> <new_file> <out.img> - replace one file
  repack  <input_dir/> <output.img>               - repack extracted dir
"""

import argparse
import os
import struct
import sys

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

IMAGEWTY_MAGIC = b"IMAGEWTY"
IMAGEWTY_MAGIC_LEN = 8
FILE_HDR_SIZE = 1024  # each file header is exactly 1024 bytes
MAIN_HDR_PAD = 1024  # main header is padded to 1024 bytes in the file
FILE_DATA_ALIGN = 512  # file data is 512-byte aligned

# Version constants
HDR_V1_SIZE = 0x50
HDR_V3_SIZE = 0x60

# ──────────────────────────────────────────────────────────────────────────────
# Header parsing
# ──────────────────────────────────────────────────────────────────────────────


def _align_up(value, alignment):
    """Round value up to the nearest multiple of alignment."""
    return (value + alignment - 1) & ~(alignment - 1)


def parse_main_header(data):
    """
    Parse the main IMAGEWTY header from bytes.
    Returns a dict with all fields.
    Raises ValueError on invalid magic or unknown format.
    """
    if len(data) < 32:
        raise ValueError("Data too short to contain IMAGEWTY header")

    magic = data[0:8]
    if magic != IMAGEWTY_MAGIC:
        # Could be RC6-encrypted
        raise ValueError(
            "Magic mismatch: expected 'IMAGEWTY', got %r\n"
            "This image may be RC6-encrypted. Decryption is not supported." % magic
        )

    hdr_ver, hdr_size, ram_base, version, image_size, image_header_size = (
        struct.unpack_from("<IIIIII", data, 8)
    )

    # Determine union layout by header_size (not header_version, since we see 0x0415)
    # 0x50 = v1 layout, 0x60 = v3 layout (also used by newer versions like 0x0415)
    if hdr_size == HDR_V1_SIZE:
        layout = "v1"
        pid, vid, hw_id, fw_id, val1, val1024, num_files, val1024_2, v0, v1, v2, v3 = (
            struct.unpack_from("<IIIIIIIIIIII", data, 32)
        )
        unknown = 0
    elif hdr_size >= HDR_V3_SIZE:
        layout = "v3"
        (
            unknown,
            pid,
            vid,
            hw_id,
            fw_id,
            val1,
            val1024,
            num_files,
            val1024_2,
            v0,
            v1,
            v2,
            v3,
        ) = struct.unpack_from("<IIIIIIIIIIIII", data, 32)
    else:
        raise ValueError("Unrecognised header_size 0x%X" % hdr_size)

    # Preserve the raw header bytes for faithful repack (includes any padding/extra data)
    raw_header = bytes(data[:MAIN_HDR_PAD])

    return {
        "magic": magic,
        "header_version": hdr_ver,
        "header_size": hdr_size,
        "layout": layout,
        "ram_base": ram_base,
        "version": version,
        "image_size": image_size,
        "image_header_size": image_header_size,
        "unknown": unknown,
        "pid": pid,
        "vid": vid,
        "hardware_id": hw_id,
        "firmware_id": fw_id,
        "val1": val1,
        "val1024": val1024,
        "num_files": num_files,
        "val1024_2": val1024_2,
        "val0": (v0, v1, v2, v3),
        "raw_header": raw_header,
    }


def build_main_header(hdr):
    """
    Rebuild the 1024-byte main header block from a parsed header dict.
    Preserves all original bytes except the fields we explicitly update.
    """
    # Start from original raw bytes so all padding/unknown fields are preserved
    buf = bytearray(hdr["raw_header"])

    # Rewrite known fields at known positions
    struct.pack_into("<8s", buf, 0, hdr["magic"])
    struct.pack_into("<I", buf, 8, hdr["header_version"])
    struct.pack_into("<I", buf, 12, hdr["header_size"])
    struct.pack_into("<I", buf, 16, hdr["ram_base"])
    struct.pack_into("<I", buf, 20, hdr["version"])
    struct.pack_into("<I", buf, 24, hdr["image_size"])
    struct.pack_into("<I", buf, 28, hdr["image_header_size"])

    if hdr["layout"] == "v1":
        struct.pack_into(
            "<IIIIIIIIIIII",
            buf,
            32,
            hdr["pid"],
            hdr["vid"],
            hdr["hardware_id"],
            hdr["firmware_id"],
            hdr["val1"],
            hdr["val1024"],
            hdr["num_files"],
            hdr["val1024_2"],
            *hdr["val0"],
        )
    else:  # v3
        struct.pack_into(
            "<IIIIIIIIIIIII",
            buf,
            32,
            hdr["unknown"],
            hdr["pid"],
            hdr["vid"],
            hdr["hardware_id"],
            hdr["firmware_id"],
            hdr["val1"],
            hdr["val1024"],
            hdr["num_files"],
            hdr["val1024_2"],
            *hdr["val0"],
        )

    return bytes(buf)


# ──────────────────────────────────────────────────────────────────────────────
# File header parsing
# ──────────────────────────────────────────────────────────────────────────────


def parse_file_header(data, offset, layout):
    """
    Parse a single 1024-byte file header at the given offset.
    Returns a dict with all fields plus 'raw_header' for faithful repack.
    """
    raw = bytes(data[offset : offset + FILE_HDR_SIZE])

    filename_len, total_header_size = struct.unpack_from("<II", raw, 0)
    maintype = raw[8:16].rstrip(b"\x00").decode("ascii", errors="replace")
    subtype = raw[16:32].rstrip(b"\x00").decode("ascii", errors="replace")

    if layout == "v1":
        # v1: [32] unknown_3, stored_len, original_len, file_offset, unknown, filename[256]
        unknown_3, stored_len, original_len, file_offset, unknown_end = (
            struct.unpack_from("<IIIII", raw, 32)
        )
        filename_bytes = raw[52 : 52 + 256]
    else:
        # v3: [32] unknown_0, filename[256], stored_len, pad1, original_len, pad2, file_offset
        unknown_3 = struct.unpack_from("<I", raw, 32)[0]
        filename_bytes = raw[36 : 36 + 256]
        stored_len, pad1, original_len, pad2, file_offset = struct.unpack_from(
            "<IIIII", raw, 36 + 256
        )
        unknown_end = 0

    filename = filename_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")

    return {
        "filename_len": filename_len,
        "total_header_size": total_header_size,
        "maintype": maintype,
        "subtype": subtype,
        "unknown_3": unknown_3,
        "stored_length": stored_len,
        "original_length": original_len,
        "offset": file_offset,
        "unknown_end": unknown_end,
        "filename": filename,
        "raw_header": raw,
    }


def build_file_header(fhdr, layout):
    """
    Rebuild the 1024-byte file header from a dict.
    Preserves original raw bytes except explicitly updated fields.
    """
    buf = bytearray(fhdr["raw_header"])

    # Common fields
    struct.pack_into("<I", buf, 0, fhdr["filename_len"])
    struct.pack_into("<I", buf, 4, fhdr["total_header_size"])
    # maintype and subtype are fixed-width, pad with nulls
    maintype_b = (
        fhdr["maintype"].encode("ascii", errors="replace").ljust(8, b"\x00")[:8]
    )
    subtype_b = (
        fhdr["subtype"].encode("ascii", errors="replace").ljust(16, b"\x00")[:16]
    )
    buf[8:16] = maintype_b
    buf[16:32] = subtype_b

    if layout == "v1":
        struct.pack_into("<I", buf, 32, fhdr["unknown_3"])
        struct.pack_into("<I", buf, 36, fhdr["stored_length"])
        struct.pack_into("<I", buf, 40, fhdr["original_length"])
        struct.pack_into("<I", buf, 44, fhdr["offset"])
        struct.pack_into("<I", buf, 48, fhdr["unknown_end"])
        fname_b = (
            fhdr["filename"].encode("utf-8", errors="replace").ljust(256, b"\x00")[:256]
        )
        buf[52 : 52 + 256] = fname_b
    else:
        # v3
        struct.pack_into("<I", buf, 32, fhdr["unknown_3"])
        fname_b = (
            fhdr["filename"].encode("utf-8", errors="replace").ljust(256, b"\x00")[:256]
        )
        buf[36 : 36 + 256] = fname_b
        pos = 36 + 256  # = 292
        existing = struct.unpack_from("<IIIII", buf, pos)
        # pad1 and pad2 are preserved from original
        struct.pack_into("<I", buf, pos + 0, fhdr["stored_length"])
        struct.pack_into("<I", buf, pos + 4, existing[1])  # pad1 preserved
        struct.pack_into("<I", buf, pos + 8, fhdr["original_length"])
        struct.pack_into("<I", buf, pos + 12, existing[3])  # pad2 preserved
        struct.pack_into("<I", buf, pos + 16, fhdr["offset"])

    return bytes(buf)


# ──────────────────────────────────────────────────────────────────────────────
# Image reading
# ──────────────────────────────────────────────────────────────────────────────


def read_image(image_path):
    """
    Open and parse an IMAGEWTY image file.
    Returns (main_header_dict, list_of_file_header_dicts).
    Does NOT load file data into memory.
    """
    with open(image_path, "rb") as f:
        # Read enough for main header + all file headers
        # We'll peek at the main header first to get num_files
        header_block = f.read(MAIN_HDR_PAD)

    main_hdr = parse_main_header(header_block)
    num_files = main_hdr["num_files"]
    layout = main_hdr["layout"]

    # Read all file headers
    file_headers_size = num_files * FILE_HDR_SIZE
    file_hdr_data_size = MAIN_HDR_PAD + file_headers_size

    with open(image_path, "rb") as f:
        all_data = f.read(file_hdr_data_size)

    file_headers = []
    for i in range(num_files):
        off = MAIN_HDR_PAD + i * FILE_HDR_SIZE
        fh = parse_file_header(all_data, off, layout)
        file_headers.append(fh)

    return main_hdr, file_headers


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


def cmd_list(image_path):
    """List all files/partitions in the image."""
    main_hdr, file_headers = read_image(image_path)

    print("IMAGEWTY Image: %s" % image_path)
    print("  Header version : 0x%04X" % main_hdr["header_version"])
    print(
        "  Header layout  : %s (size=0x%02X)"
        % (main_hdr["layout"], main_hdr["header_size"])
    )
    print(
        "  Image size     : %d bytes (%.1f MB)"
        % (main_hdr["image_size"], main_hdr["image_size"] / (1024 * 1024))
    )
    print("  PID/VID        : 0x%04X / 0x%04X" % (main_hdr["pid"], main_hdr["vid"]))
    print("  Num files      : %d" % main_hdr["num_files"])
    print()

    # Column widths
    print(
        "%-4s  %-40s  %-18s  %-18s  %12s  %12s  %12s"
        % ("#", "Filename", "Maintype", "Subtype", "Stored", "Original", "Offset")
    )
    print("-" * 130)

    for i, fh in enumerate(file_headers):
        print(
            "%-4d  %-40s  %-18s  %-18s  %12d  %12d  0x%010X"
            % (
                i,
                fh["filename"][:40],
                fh["maintype"][:18],
                fh["subtype"][:18],
                fh["stored_length"],
                fh["original_length"],
                fh["offset"],
            )
        )


def cmd_extract(image_path, output_dir):
    """Extract all files from the image into output_dir."""
    main_hdr, file_headers = read_image(image_path)

    os.makedirs(output_dir, exist_ok=True)

    # Save metadata for reliable repack
    meta_path = os.path.join(output_dir, "_imagewty_meta.bin")
    with open(meta_path, "wb") as mf:
        # Save raw main header (1024 bytes)
        mf.write(main_hdr["raw_header"])
        # Save all raw file headers (each 1024 bytes)
        for fh in file_headers:
            mf.write(fh["raw_header"])
    print("Saved metadata: %s" % meta_path)

    with open(image_path, "rb") as img:
        for i, fh in enumerate(file_headers):
            fname = fh["filename"]

            # Sanitise filename: replace path separators, handle empty names
            safe_fname = fname.replace("/", "_").replace("\\", "_").strip()
            if not safe_fname:
                safe_fname = "file_%04d" % i

            out_path = os.path.join(output_dir, safe_fname)

            img.seek(fh["offset"])
            file_data = img.read(fh["original_length"])

            with open(out_path, "wb") as out:
                out.write(file_data)

            print(
                "[%3d/%d] %-40s -> %s  (%d bytes)"
                % (i + 1, len(file_headers), fname, safe_fname, fh["original_length"])
            )

    print("\nExtracted %d files to: %s" % (len(file_headers), output_dir))


def cmd_replace(image_path, target_filename, new_file_path, output_path):
    """
    Replace one file in the image and write to a new image file.
    Strategy: copy the original image byte-for-byte, then patch only the
    file header and file data for the replaced partition. This preserves
    all gaps, padding, checksums, and unknown structures exactly.
    """
    main_hdr, file_headers = read_image(image_path)
    layout = main_hdr["layout"]

    # Find the target file
    target_idx = None
    for i, fh in enumerate(file_headers):
        if fh["filename"] == target_filename:
            target_idx = i
            break

    if target_idx is None:
        # Try case-insensitive match
        for i, fh in enumerate(file_headers):
            if fh["filename"].lower() == target_filename.lower():
                target_idx = i
                print(
                    "Warning: matched '%s' case-insensitively (original: '%s')"
                    % (target_filename, fh["filename"])
                )
                break

    if target_idx is None:
        print("Error: file '%s' not found in image." % target_filename)
        print("Use 'list' command to see available files.")
        sys.exit(1)

    with open(new_file_path, "rb") as nf:
        new_data = nf.read()

    new_original_length = len(new_data)
    old_fh = file_headers[target_idx]

    # For in-place replace, the new file MUST fit within the original stored_length.
    # If it's the same size (typical for boot images), this is trivially true.
    # If larger, we cannot do a safe in-place replace.
    new_stored_length = _align_up(new_original_length, FILE_DATA_ALIGN)

    if new_stored_length > old_fh["stored_length"]:
        print(
            "Error: new file (%d bytes stored) is LARGER than original slot (%d bytes)."
            % (new_stored_length, old_fh["stored_length"])
        )
        print(
            "In-place replacement is not possible. The file must fit within the original partition size."
        )
        sys.exit(1)

    print("Replacing '%s':" % old_fh["filename"])
    print(
        "  Old: stored=%d  original=%d  offset=0x%X"
        % (old_fh["stored_length"], old_fh["original_length"], old_fh["offset"])
    )
    print("  New: stored=%d  original=%d" % (new_stored_length, new_original_length))

    # Step 1: Copy original image byte-for-byte
    import shutil

    print("  Copying original image...")
    shutil.copy2(image_path, output_path)

    # Step 2: Patch the file header for this partition
    new_fh = dict(old_fh)
    new_fh["stored_length"] = old_fh["stored_length"]  # keep original slot size
    new_fh["original_length"] = new_original_length
    # offset stays the same

    file_header_offset = MAIN_HDR_PAD + target_idx * FILE_HDR_SIZE
    patched_header = build_file_header(new_fh, layout)

    with open(output_path, "r+b") as out:
        # Write patched file header
        out.seek(file_header_offset)
        out.write(patched_header)

        # Step 3: Write new file data at the original offset, zero-pad remainder
        out.seek(old_fh["offset"])
        out.write(new_data)
        # Zero-pad the rest of the original slot
        remaining = old_fh["stored_length"] - new_original_length
        if remaining > 0:
            out.write(b"\x00" * remaining)

        # Step 4: Update the verification checksum (V-prefixed file)
        # Allwinner uses sum of all uint32 LE words as checksum, stored in a
        # small V-prefixed companion file (e.g. Vboot.fex for boot.fex)
        verify_name = "V" + old_fh["filename"]
        verify_idx = None
        for vi, vfh in enumerate(file_headers):
            if vfh["filename"] == verify_name:
                verify_idx = vi
                break

        if verify_idx is not None:
            # Calculate new checksum: sum of all uint32 LE words
            # Pad new_data to multiple of 4 bytes if needed
            padded = new_data
            pad_remainder = len(padded) % 4
            if pad_remainder:
                padded = padded + b"\x00" * (4 - pad_remainder)
            checksum = 0
            for wi in range(0, len(padded), 4):
                checksum = (
                    checksum + struct.unpack_from("<I", padded, wi)[0]
                ) & 0xFFFFFFFF
            new_checksum_bytes = struct.pack("<I", checksum)

            verify_fh = file_headers[verify_idx]
            out.seek(verify_fh["offset"])
            out.write(new_checksum_bytes)
            print(
                "  Updated checksum: %s -> %s" % (verify_name, new_checksum_bytes.hex())
            )
        else:
            print("  Warning: no verification file '%s' found" % verify_name)

    print("\nNew image written to: %s" % output_path)
    print("  Size: %d bytes (identical to original)" % os.path.getsize(output_path))


def cmd_repack(input_dir, output_path):
    """
    Repack an extracted directory back into an IMAGEWTY image.
    Requires _imagewty_meta.bin to be present (created by extract).
    """
    meta_path = os.path.join(input_dir, "_imagewty_meta.bin")
    if not os.path.exists(meta_path):
        print("Error: '%s' not found." % meta_path)
        print("The input directory must be created by 'extract' command.")
        sys.exit(1)

    with open(meta_path, "rb") as mf:
        meta_data = mf.read()

    # Parse main header from saved metadata
    main_hdr = parse_main_header(meta_data[:MAIN_HDR_PAD])
    num_files = main_hdr["num_files"]
    layout = main_hdr["layout"]

    # Parse file headers from saved metadata
    original_file_headers = []
    for i in range(num_files):
        off = MAIN_HDR_PAD + i * FILE_HDR_SIZE
        fh = parse_file_header(meta_data, off, layout)
        original_file_headers.append(fh)

    # Determine current data for each file
    updated_file_data = []
    updated_file_headers = []

    current_offset = MAIN_HDR_PAD + num_files * FILE_HDR_SIZE

    for i, fh in enumerate(original_file_headers):
        fname = fh["filename"]
        safe_fname = fname.replace("/", "_").replace("\\", "_").strip()
        if not safe_fname:
            safe_fname = "file_%04d" % i

        file_path = os.path.join(input_dir, safe_fname)

        if os.path.exists(file_path):
            with open(file_path, "rb") as fp:
                file_data = fp.read()
        else:
            print(
                "Warning: '%s' not found, using zero-filled placeholder of original size %d"
                % (file_path, fh["original_length"])
            )
            file_data = b"\x00" * fh["original_length"]

        original_len = len(file_data)
        stored_len = _align_up(original_len, FILE_DATA_ALIGN)

        new_fh = dict(fh)
        new_fh["original_length"] = original_len
        new_fh["stored_length"] = stored_len
        new_fh["offset"] = current_offset

        updated_file_headers.append(new_fh)
        updated_file_data.append((file_data, stored_len))

        current_offset += stored_len

    # Update image_size
    new_main_hdr = dict(main_hdr)
    new_main_hdr["image_size"] = current_offset
    new_main_hdr["num_files"] = num_files

    # Write the image
    with open(output_path, "wb") as out:
        # Main header
        out.write(build_main_header(new_main_hdr))

        # File headers
        for fh in updated_file_headers:
            out.write(build_file_header(fh, layout))

        # File data
        for i, (file_data, stored_len) in enumerate(updated_file_data):
            out.write(file_data)
            padding = stored_len - len(file_data)
            if padding > 0:
                out.write(b"\x00" * padding)

    total_size = os.path.getsize(output_path)
    print("Repacked %d files into: %s" % (num_files, output_path))
    print("Image size: %d bytes (%.1f MB)" % (total_size, total_size / (1024 * 1024)))


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Allwinner IMAGEWTY firmware image tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python awimg.py list update.img
  python awimg.py extract update.img output_dir/
  python awimg.py replace update.img boot.fex new_boot.img output.img
  python awimg.py repack output_dir/ new_update.img
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List all files in the image")
    p_list.add_argument("image", help="Path to .img file")

    # extract
    p_extract = subparsers.add_parser(
        "extract", help="Extract all files from the image"
    )
    p_extract.add_argument("image", help="Path to .img file")
    p_extract.add_argument("output_dir", help="Output directory")

    # replace
    p_replace = subparsers.add_parser(
        "replace", help="Replace one file and write a new image"
    )
    p_replace.add_argument("image", help="Path to input .img file")
    p_replace.add_argument("filename", help="Filename to replace (as shown by 'list')")
    p_replace.add_argument("new_file", help="Path to new file content")
    p_replace.add_argument("output", help="Path for output .img file")

    # repack
    p_repack = subparsers.add_parser(
        "repack", help="Repack an extracted directory into an image"
    )
    p_repack.add_argument("input_dir", help="Directory created by 'extract'")
    p_repack.add_argument("output", help="Path for output .img file")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args.image)
    elif args.command == "extract":
        cmd_extract(args.image, args.output_dir)
    elif args.command == "replace":
        cmd_replace(args.image, args.filename, args.new_file, args.output)
    elif args.command == "repack":
        cmd_repack(args.input_dir, args.output)


if __name__ == "__main__":
    main()
