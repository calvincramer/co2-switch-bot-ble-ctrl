#!/usr/bin/env python3

"""
Extract the btsnooz blob from an Android bugreport or `dumpsys bluetooth_manager`
dump and convert it to a btsnoop file that Wireshark can open.

Since Android 9 the HCI snoop log is no longer shipped as a plain file inside the
bugreport. It is embedded in the text as a zlib-compressed, base64-encoded ring
buffer between the BTSNOOP_LOG_SUMMARY markers. This is a Python 3 port of AOSP's
tools/scripts/btsnooz.py.

    btsnooz = base64 { file_header deflate { repeated { record_header record_data } } }

Usage:
    adb shell dumpsys bluetooth_manager > dump.txt
    ./btsnooz.py dump.txt -o capture.btsnoop
"""

from __future__ import annotations

import argparse
import base64
import collections
import struct
import sys
import zlib
from pathlib import Path

BEGIN_MARKER = "--- BEGIN:BTSNOOP_LOG_SUMMARY"
END_MARKER = "--- END:BTSNOOP_LOG_SUMMARY"

# The 'type' field of a btsnooz record, from the Bluetooth stack's internal
# representation of packet types.
TYPE_IN_EVT = 0x10
TYPE_IN_ACL = 0x11
TYPE_IN_SCO = 0x12
TYPE_IN_ISO = 0x17
TYPE_OUT_CMD = 0x20
TYPE_OUT_ACL = 0x21
TYPE_OUT_SCO = 0x22
TYPE_OUT_ISO = 0x2D

INBOUND_TYPES = {TYPE_IN_EVT, TYPE_IN_ACL, TYPE_IN_SCO, TYPE_IN_ISO}

# The blob header carries the last packet's time as microseconds since the Unix
# epoch, and the per-record deltas are microseconds too. btsnoop wants microseconds
# since 0000-01-01, so everything just needs this one epoch shift.
EPOCH_OFFSET = 0x00DCDDB30F2F8000

# "btsnoop\0", version 1, datalink type 1002 (H4 UART)
BTSNOOP_HEADER = b"btsnoop\x00\x00\x00\x00\x01\x00\x00\x03\xea"

HCI_TYPE = {
    TYPE_OUT_CMD: b"\x01",
    TYPE_IN_ACL: b"\x02",
    TYPE_OUT_ACL: b"\x02",
    TYPE_IN_SCO: b"\x03",
    TYPE_OUT_SCO: b"\x03",
    TYPE_IN_EVT: b"\x04",
    TYPE_IN_ISO: b"\x05",
    TYPE_OUT_ISO: b"\x05",
}

# Record header layouts. The btsnooz version byte does not pin these down: Qualcomm
# builds (libbluetooth_qti.so) widen the delta to 64 bits and move the type byte to
# the head of the record data, so the layout has to be detected rather than assumed.
#
#   name       struct   fields                                        type byte
#   v1         =HIb     length, delta_us, type                        in header
#   v2         =HHIb    length, packet_length, delta_us, type         in header
#   v2-u64     =HHQ     length, packet_length, delta_us (64-bit)      first data byte
Layout = collections.namedtuple("Layout", "name fmt type_in_data has_packet_length")

LAYOUTS = [
    Layout("v2-u64", "=HHQ", True, True),
    Layout("v2", "=HHIb", False, True),
    Layout("v1", "=HIb", False, False),
]


def extract_blob(text: str) -> bytes | None:
    """Pull the base64 payload from between the BTSNOOP_LOG_SUMMARY markers"""
    start = text.find(BEGIN_MARKER)
    if start == -1:
        return None
    start = text.find("\n", start) + 1
    end = text.find(END_MARKER, start)
    if end == -1:
        return None
    return base64.standard_b64decode("".join(text[start:end].split()))


def iter_records(decompressed: bytes, layout: Layout):
    """Walk the record stream, yielding (length, packet_length, delta_time_us, type, payload)"""
    header_size = struct.calcsize(layout.fmt)
    offset = 0
    while offset < len(decompressed):
        fields = struct.unpack_from(layout.fmt, decompressed, offset)
        if layout.has_packet_length:
            length, packet_length, delta_time_us = fields[0], fields[1], fields[2]
        else:
            length, packet_length, delta_time_us = fields[0], fields[0], fields[1]
        offset += header_size
        # In every layout `length` counts the HCI type byte, which is either carried
        # in the record header or stored as the first byte of the record data.
        if layout.type_in_data:
            snooz_type = decompressed[offset]
            payload = decompressed[offset + 1 : offset + length]
        else:
            snooz_type = fields[-1]
            payload = decompressed[offset : offset + length - 1]
        offset += length - 1 if not layout.type_in_data else length
        yield length, packet_length, delta_time_us, snooz_type, payload


def detect_layout(decompressed: bytes) -> Layout:
    """Pick the record layout that walks the buffer exactly, with only known packet types"""
    for layout in LAYOUTS:
        header_size = struct.calcsize(layout.fmt)
        offset = 0
        records = 0
        try:
            while offset < len(decompressed):
                fields = struct.unpack_from(layout.fmt, decompressed, offset)
                length = fields[0]
                snooz_type = decompressed[offset + header_size] if layout.type_in_data else fields[-1]
                if snooz_type not in HCI_TYPE or length < 1:
                    break
                offset += header_size + (length if layout.type_in_data else length - 1)
                records += 1
            else:
                # Every record parsed with a known type. The walk is only trustworthy
                # if it landed exactly on the end of the buffer rather than past it.
                if offset == len(decompressed) and records:
                    return layout
        except (struct.error, IndexError):
            continue
    raise ValueError("could not determine btsnooz record layout")


def decode_snooz(snooz: bytes, layout: Layout | None = None) -> tuple[bytes, Layout, int]:
    """Convert a raw btsnooz blob into btsnoop file contents"""
    version, last_timestamp_us = struct.unpack_from("=bQ", snooz)
    if version not in (1, 2):
        raise ValueError(f"unsupported btsnooz version: {version}")

    # The 9-byte file header is not compressed, but everything after it is.
    decompressed = zlib.decompress(snooz[9:])
    if layout is None:
        layout = detect_layout(decompressed)

    # The format only stores the timestamp of the *last* packet plus per-record
    # deltas, so walk the whole stream backwards to find where it started.
    timestamp_us = last_timestamp_us + EPOCH_OFFSET
    for _, _, delta_time_us, _, _ in iter_records(decompressed, layout):
        timestamp_us -= delta_time_us

    out = bytearray(BTSNOOP_HEADER)
    count = 0
    for length, packet_length, delta_time_us, snooz_type, payload in iter_records(decompressed, layout):
        timestamp_us += delta_time_us
        hci = HCI_TYPE.get(snooz_type)
        if hci is None:
            raise ValueError(f"unknown btsnooz record type 0x{snooz_type:02x}")
        direction = 1 if snooz_type in INBOUND_TYPES else 0
        # original length, included length, flags, cumulative drops, timestamp
        out += struct.pack(">IIIIq", packet_length, length, direction, 0, timestamp_us)
        out += hci
        out += payload
        count += 1
    return bytes(out), layout, count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert an Android btsnooz blob into a btsnoop capture.")
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="bugreport txt or dumpsys output (default: stdin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("capture.btsnoop"),
        metavar="PATH",
        help="where to write the btsnoop file (default capture.btsnoop)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.input is None:
        text = sys.stdin.read()
    else:
        text = args.input.read_text(encoding="latin-1", errors="replace")

    blob = extract_blob(text)
    if blob is None:
        print("No BTSNOOP_LOG_SUMMARY section found.", file=sys.stderr)
        return 1

    snoop, layout, packets = decode_snooz(blob)
    args.output.write_bytes(snoop)

    print(
        f"{args.output}: {packets} packets, {len(snoop)} bytes (btsnooz layout {layout.name})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
