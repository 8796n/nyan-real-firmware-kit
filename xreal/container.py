#!/usr/bin/env python3
"""The XREAL firmware container format: header, CRC-32 and bank0 commit tag.

Both the DP bridge image and the MCU image use the same container, and the
flashers here validate an image before writing a single byte of it.

Layout of the first 0x40 bytes:

    [0x00:0x04]  CRC-32 over d[8 : 8+length]        DP: little-endian
    [0x04:0x08]  length, little-endian
    [0x08:0x0C]  project code -- which model this image is for
    [0x0C:0x10]  firmware type (2 = DP bridge)
    [0x10:0x24]  name, NUL terminated ("1140")
    [0x24:0x32]  build string
    [0x38]       bank0 commit tag

The bank0 tag is a CRC-8 over the payload padded with 0xFF up to 64 KiB minus
one byte, and the DP7911 boot checks it. If it does not match, the bridge
rejects bank0 and boots an internal fallback image instead.

The image builders under each model directory carry their own copy of these
routines on purpose: a builder should be auditable as a single file. This
module exists so the flashers do not need one.
"""
import struct
import sys

HDR = 0x40                 # code address = file offset - 0x40
POLY = 0xF4ACFB13          # container CRC-32
TAG_OFF = 0x38             # bank0 commit tag
TAG_POLY = 0x31            # bank0 tag CRC-8
BANK0 = 0x10000            # the tag is burned at the last byte of bank0


def crc_container(data: bytes) -> int:
    """CRC-32 / poly 0xF4ACFB13 / MSB-first / init 0 / no reflection / xorout 0."""
    c = 0
    for b in data:
        c ^= b << 24
        for _ in range(8):
            c = ((c << 1) ^ POLY) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c


def crc8_tag(data: bytes) -> int:
    """CRC-8 / poly 0x31 / init 0 / MSB-first / no reflection / xorout 0."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ TAG_POLY) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def head(d: bytes) -> dict:
    return dict(
        stored_crc=struct.unpack_from("<I", d, 0)[0],
        length=struct.unpack_from("<I", d, 4)[0],
        project=struct.unpack_from("<I", d, 8)[0],
        fwtype=struct.unpack_from("<I", d, 12)[0],
        name=d[16:36].split(b"\0")[0].decode("ascii", "replace"),
        build=d[36:50].split(b"\0")[0].decode("ascii", "replace"),
    )


def calc_bank0_tag(d: bytes) -> int:
    """CRC-8 over the payload (file 0x40..EOF) padded with 0xFF to 64 KiB - 1."""
    payload = bytes(d[HDR:])
    pad = BANK0 - 1 - len(payload)
    if pad < 0:
        sys.exit("payload exceeds bank0 (64 KiB - 1): %d bytes" % len(payload))
    return crc8_tag(payload + b"\xFF" * pad)


def bank0_ok(d: bytes) -> bool:
    """True when the whole of bank0, tag included, has CRC-8 zero.

    This is the same test the DP7911 boot performs.
    """
    payload = bytes(d[HDR:])
    pad = BANK0 - 1 - len(payload)
    return crc8_tag(payload + b"\xFF" * pad + bytes([d[TAG_OFF]])) == 0
