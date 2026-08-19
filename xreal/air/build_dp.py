#!/usr/bin/env python3
r"""Build the XREAL Air (gen 1) DP bridge image.

WHAT THIS DOES
    Takes the *official* DP7911 firmware container for the Air gen 1 -- the file
    the vendor ships, named ``1140`` -- and applies 39 byte-level records so the
    glasses handle four input paths properly instead of one:

        1280x720            for HDMI converters and consoles that only do 720p
        1920x1080           unchanged, still native
        1920x1200           the panels' real geometry, now the preferred timing
        3840x1200 Full-SBS  side-by-side 3D at 60 / 72 / 90 Hz over HBR2

    Stock firmware advertises 1080p only, so 1200p is never offered and 720p
    sources get no matching timing. This build advertises all of them, and the
    fixed-refresh modes stop leaking a CTA block that let hosts pick unrelated
    refresh rates.

    The stock container carries the EDID templates of several models -- the
    projectCode in the header is what selects one.  This build touches only the
    Air gen 1 template; the Air 2 / HONOR / Air 2 Pro / Air 2 Ultra blocks are
    left byte-identical to stock.

WHAT THIS DOES NOT DO
    It does not download, embed, or redistribute any vendor firmware, and it
    never touches hardware.  You supply the stock container yourself with
    ``--src``; the tool refuses anything whose SHA-256 is not the expected one.
    Flashing is a separate tool and is entirely at your own risk.

VERIFICATION
    Building is the easy half.  The script also proves the result:

      * the stock input must hash to STOCK_SHA256
      * every record's "before" bytes must match before it is applied
      * the rebuild is deterministic and its SHA / container CRC / bank0 tag /
        changed-byte count are all pinned
      * the resulting EDID is decoded and checked against the advertised
        contract, per logical mode
      * the 8051 post-build helper is *executed* in a small emulator over every
        E0BF / E0B9 / E0BB vector, to prove which base DTD slots it writes

    A mismatch anywhere is a hard failure.  There is no --force.

This file is self-contained: standard library only, no imports from the
research tree it was distilled from.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

# --- container ---------------------------------------------------------------
HDR = 0x40                 # code address = file offset - 0x40
POLY = 0xF4ACFB13          # container CRC-32
TAG_OFF = 0x38             # bank0 commit tag
TAG_POLY = 0x31            # bank0 tag CRC-8
BANK0 = 0x10000            # tag is burned at the last byte of bank0

SIZE = 50_632
STOCK_SHA256 = "66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA"
OUTPUT_SHA256 = "D5D34FB0ED0AB49B92D793CCF8384E61B1C1274AAC45293911F3CAF325BDC793"
OUTPUT_CRC = 0xE888FA07
OUTPUT_TAG = 0x1A
EXPECTED_DIFFS = 913       # bytes that actually change, incl. container CRC and tag
                           # (the records span 1025 bytes; some are unchanged inside a span)

EXPECT_PROJECT = 0x0700    # air gen 1.  Flashing another project code bricks it.
EXPECT_FWTYPE = 2          # dp
EXPECT_NAME = "1140"

Record = tuple[str, int, bytes, bytes]


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


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
    )


def fix_container_crc(d: bytearray) -> int:
    crc = crc_container(bytes(d[8:8 + head(bytes(d))["length"]]))
    struct.pack_into("<I", d, 0, crc)
    return crc


def fix_bank0_tag(d: bytearray) -> int:
    payload = bytes(d[HDR:])
    pad = BANK0 - 1 - len(payload)
    if pad < 0:
        fail("payload exceeds bank0")
    d[TAG_OFF] = crc8_tag(payload + b"\xFF" * pad)
    return d[TAG_OFF]


def validate_container(d: bytes, what: str) -> None:
    if len(d) != SIZE:
        fail(f"{what}: expected {SIZE} bytes, got {len(d)}")
    h = head(d)
    if h["project"] != EXPECT_PROJECT:
        fail(f"{what}: projectCode 0x{h['project']:04X} is not Air gen 1 (0x0700). "
             "Flashing another model's image will brick it.")
    if h["fwtype"] != EXPECT_FWTYPE or h["name"] != EXPECT_NAME:
        fail(f"{what}: fwType/name mismatch ({h['fwtype']} / {h['name']!r})")
    if crc_container(d[8:8 + h["length"]]) != h["stored_crc"]:
        fail(f"{what}: container CRC-32 does not match its header")


# --- the change set ----------------------------------------------------------
# Offsets are file offsets in the container.  "code" addresses referenced in the
# labels are file - 0x40.  Every record is a verbatim before/after pair, so the
# whole change set is auditable by diffing this table against the two images.

RECORDS: tuple[Record, ...] = (
    ("scaler workspace source plane0 -> zero padding 0x44C2",
     0x00099,
     bytes.fromhex("347907"),
     bytes.fromhex("4479c2")),
    ("scaler workspace source plane1 -> zero padding 0x4502",
     0x000AC,
     bytes.fromhex("347947"),
     bytes.fromhex("457902")),
    ("scaler workspace source plane2 -> zero padding 0x4542",
     0x000BF,
     bytes.fromhex("347987"),
     bytes.fromhex("457942")),
    ("scaler fixed totals -> measured input totals from E790:E793",
     0x00318,
     bytes.fromhex("0474121b220000044c900474121afe7801121ab1900474121b16900488121b2200000465900488121afe900470121b16900488121afe90048c121b16"),
     bytes.fromhex("e790e0fe90e791e0ffe4fcfd900474121b1690e792e0fe90e793e0ffe4fcfd900488121b16900470121b1690048c121b160000000000000000000000")),
    ("v31 horizontal endpoint ratio",
     0x006DE,
     bytes.fromhex("ffffee34fffeed34fffdec34ff"),
     bytes.fromhex("00ffee3400feed3400fdec3400")),
    ("v31 vertical endpoint ratio",
     0x007B6,
     bytes.fromhex("ffffee34fffeed34fffdec34ff"),
     bytes.fromhex("00ffee3400feed3400fdec3400")),
    ("mode1 initializer: 1200-line geometry",
     0x0115C,
     bytes.fromhex("0c"),
     bytes.fromhex("0f")),
    ("mode1 initializer: Vtotal/Vactive 1125/1080 -> 1250/1200",
     0x011B5,
     bytes.fromhex("65f0a37404f0a37438f0a3e4f0a37404"),
     bytes.fromhex("e2f0a37404f0a374b0f0a3e4f0a37409")),
    ("mode1 DTD0 pclk 148.500 -> 165.000 MHz",
     0x011E2,
     bytes.fromhex("4414"),
     bytes.fromhex("8488")),
    ("mode1 DTD1 pclk 222.750 -> 247.500 MHz",
     0x011EF,
     bytes.fromhex("661e"),
     bytes.fromhex("c6cc")),
    ("mode1 DTD2 pclk 297.000 -> 330.000 MHz",
     0x01201,
     bytes.fromhex("048828"),
     bytes.fromhex("050910")),
    ("shared V tail -> 2D/3D split helper (SBS 1200 HBR2)",
     0x014CD,
     bytes.fromhex("f0a37404f0a3"),
     bytes.fromhex("1234370214b1")),
    ("mode1-only CTA extension gate",
     0x01551,
     bytes.fromhex("f09006d07404f090e0b8e07bffb401"),
     bytes.fromhex("1234a3007404f090e0bfe07bffb402")),
    ("mode9 link rate HBR -> HBR2 (DP 1.2)",
     0x0159F,
     bytes.fromhex("0a"),
     bytes.fromhex("14")),
    ("mode9 E0BE path -> shared CTA selector",
     0x015AB,
     bytes.fromhex("01f078ab7c02fd"),
     bytes.fromhex("00f0129175801b")),
    ("normal CTA memcpy -> shared CTA selector",
     0x015BA,
     bytes.fromhex("78ab7c027d"),
     bytes.fromhex("129175800e")),
    ("post-build base DTD hook",
     0x015D5,
     bytes.fromhex("7bff7a1c79fe123fc1"),
     bytes.fromhex("1291cc000000000000")),
    ("Air Range Limits Hmax -> 153 kHz",
     0x01DBE,
     bytes.fromhex("3c"),
     bytes.fromhex("99")),
    ("Air base extension count / checksum",
     0x01DDA,
     bytes.fromhex("00a0"),
     bytes.fromhex("0142")),
    ("DP-audio CTA header",
     0x01FDE,
     bytes.fromhex("1251"),
     bytes.fromhex("1450")),
    ("DP-audio CTA: VIC4 + 1080p60/90/120",
     0x01FEE,
     bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     bytes.fromhex("4104023a801871382d40582c450080387400001e0357801871382d40582c450080387400001e0474801871382d40582c450080387400001e")),
    ("tuple / base-DTD dispatcher cave",
     0x0205B,
     bytes.fromhex("bf02030a1165030c0010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000005c"),
     bytes.fromhex("c814f8c394035035e823f890e086e06004b4022908e875f005a4f89030f5e893c0e008e893f908e893fa08e893fb08e893f5f0eb90043a1234370234b522584d801871b03240582c950080b07400001e2059445a446c702090e0b9e0701aa3a3e014fec394035010ee23f890206be893fa08e893f90291ea220000000000000000")),
    ("mode10 exact 247.500 MHz coherent helper",
     0x03135,
     bytes.fromhex("0a53616d65207265736f6c7574696f6e202c206e6f206e656564207363616c65"),
     bytes.fromhex("02b8186538030570e2b003661e653803c6cce2b00488286538050910e2b00000")),
    ("Air 2 lineage: 720p audio/RGB native return",
     0x03212,
     bytes.fromhex("0a2054686520706879636c6b207265616368206d6178696d756d2076616c75652e2e2e"),
     bytes.fromhex("9006e7e06404701490e0bbe0700ee4fc7d037e667f1e900460121b16e47f0222000000")),
    ("3D pclk/timing helper + 3D-only HBR2 helper",
     0x03447,
     bytes.fromhex("000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     bytes.fromhex("90e598e0547ff090e0bbe070189006e77402f09006d27401f090f96ce4f090f910e054fef022e5f0f090e7ceebf02200f0b4e23490e0bbe054032323f8903493e893fc08e893fd08e893fe08e893ff90042b121b1690043b7404f0a374b0f0a3e4f0a37409f0800fa37404f0a37438f0a3e4f0a37404f0a3e4f0a37405f0a3e4f0a37424f0a37401f0a3f0220005091000060ae000078d9800078d98f09006e8e0b402069006cf7414f09006d02290042cd0e0f0a3e9f0a3eaf090e7ca02342d")),
    ("no-audio CTA: VIC4 + 1200p60/90/120 + 1080p60/90/120",
     0x04484,
     bytes.fromhex("04510000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     bytes.fromhex("060141047440801871b03240582c950080b07400001eae60801871b03240582c950080b07400001ee880801871b03240582c950080b07400001e023a801871382d40582c450080387400001e0357801871382d40582c450080387400001e0474801871382d40582c450080387400001e")),
    ("no-audio CTA checksum",
     0x04501,
     bytes.fromhex("bf"),
     bytes.fromhex("22")),
    ("scaler entry guard",
     0x04B5E,
     bytes.fromhex("0c"),
     bytes.fromhex("0f")),
    ("input classifier -> vertical class helper",
     0x04D1B,
     bytes.fromhex("900448e0b4"),
     bytes.fromhex("12913c8046")),
    ("link budget 158.500 -> 175.000 MHz",
     0x04D70,
     bytes.fromhex("247a6b"),
     bytes.fromhex("987aab")),
    ("link budget 188.200 -> 208.000 MHz",
     0x04D96,
     bytes.fromhex("287adf7902"),
     bytes.fromhex("807a2c7903")),
    ("link budget 232.750 -> 257.500 MHz",
     0x04DBD,
     bytes.fromhex("2e7a8d"),
     bytes.fromhex("dc7aed")),
    ("link budget 307.000 -> 340.000 MHz",
     0x04DE4,
     bytes.fromhex("387aaf7904"),
     bytes.fromhex("207a307905")),
    ("1200-line rate classification table",
     0x04E5E,
     bytes.fromhex("9006e8e06401707b9006e7e064037073fdff12609990e598e04480f012ba26ef603690e0867402"),
     bytes.fromhex("12ba26ef607d9006e8e0640170759006e7e06404706dfdff12609990e598e04480f090e0867400")),
    ("post-copy hook -> exact-clock helper",
     0x04FD9,
     bytes.fromhex("e47f02"),
     bytes.fromhex("1231d2")),
    ("scaler workspace source plane -> zero padding 0x44C2 (site 4)",
     0x05ECF,
     bytes.fromhex("91793c"),
     bytes.fromhex("4479c2")),
    ("scaler workspace source plane -> zero padding 0x4502 (site 5)",
     0x07C5C,
     bytes.fromhex("91797d"),
     bytes.fromhex("457902")),
    ("vertical input classifier + base DTD helper + BF0 copy helper",
     0x0917C,
     bytes.fromhex("00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     bytes.fromhex("90044ae0b4040fa3e0b43803e48010b4b04774028009b40240a3e0b4d03be490e086f090e0bfe0703090e0bae0702aa3e002201c000000000078ab7c027d017bff90e0b8e0b401067a1f799c80047a4479427e007f8012179522023a801871382d40582c450080387400001e0357801871382d40582c450080387400001e0474801871382d40582c450080387400001e90e0bfe0b4021478617c027d017bff7a4479487e007f361217952202207178617c027d017bff7e007f1212179522")),
    ("720p delayed profile port count",
     0x0BA80,
     bytes.fromhex("ee33fee4b5071aeeb40f16ae04af05be040fbf380c7bff7a3079f5123fc17f0022e49006d6f07f0122"),
     bytes.fromhex("bc020cbdd0099006e77404f07f012290e0bfe0b4020d90e598e030e7061234077f00227f0022000000")),
)

RECORD_BYTES = sum(len(old) for _l, _o, old, _n in RECORDS)


def build(stock: bytes) -> bytes:
    out = bytearray(stock)
    for label, offset, old, new in RECORDS:
        if out[offset:offset + len(old)] != old:
            fail(f"stock image does not match record at 0x{offset:05X}: {label}")
        out[offset:offset + len(new)] = new
    fix_bank0_tag(out)
    fix_container_crc(out)
    return bytes(out)


# --- EDID contract -----------------------------------------------------------
# XDATA layout the firmware assembles at runtime:
#   base EDID block   0x022B
#   DTD slots         +54 / +72 / +90 / +108   (0x0261 / 0x0273 / 0x0285 / 0x0297)
#   extension count   +126
BASE_EDID = 0x022B
SLOT0 = BASE_EDID + 54
SLOT1 = BASE_EDID + 72

AIR_TEMPLATE = 0x01D5C          # static base EDID block for the Air gen 1
CTA_AUDIO = 0x01FDC             # served when E0B8 = 1 (DP audio)
CTA_NOAUDIO = 0x04482           # served when E0B8 = 0 (USB audio)
CTA_SIZE = 128

DTD_1200_60 = bytes.fromhex("7440801871b03240582c950080b07400001e")
DTD_1200_72 = bytes.fromhex("584d801871b03240582c950080b07400001e")
DTD_1200_90 = bytes.fromhex("ae60801871b03240582c950080b07400001e")
DTD_1200_120 = bytes.fromhex("e880801871b03240582c950080b07400001e")
DTD_1080_60 = bytes.fromhex("023a801871382d40582c450080387400001e")
DTD_1080_90 = bytes.fromhex("0357801871382d40582c450080387400001e")
DTD_1080_120 = bytes.fromhex("0474801871382d40582c450080387400001e")
DTDS_1200 = (DTD_1200_60, DTD_1200_90, DTD_1200_120)
DTDS_1080 = (DTD_1080_60, DTD_1080_90, DTD_1080_120)

RANGE_LIMITS = bytes.fromhex("000000fd00328214993c000a202020202020")


def cta_vics(block: bytes) -> list[int]:
    vics, i, end = [], 4, block[2]
    while i < end:
        tag, n = block[i] >> 5, block[i] & 0x1F
        if tag == 2:
            vics.extend(v & 0x7F for v in block[i + 1:i + 1 + n])
        i += 1 + n
    return vics


def cta_dtds(block: bytes) -> list[bytes]:
    out, cur = [], block[2]
    while cur + 18 <= 127:
        dtd = block[cur:cur + 18]
        if dtd == bytes(18):
            if any(block[cur:127]):
                fail("non-zero data follows the CTA DTD padding")
            break
        out.append(dtd)
        cur += 18
    return out


def verify_edid(image: bytes) -> None:
    base = image[AIR_TEMPLATE:AIR_TEMPLATE + 128]
    if sum(base) & 0xFF:
        fail("Air static base EDID checksum is not zero")
    if base[35:38] != bytes(3):
        fail("Air Established Timings are not empty")
    if base[38:54] != bytes.fromhex("0101") * 8:
        fail("Air Standard Timings are not empty (720p60 must live in the mode1 CTA only)")
    if base[90:108] != RANGE_LIMITS:
        fail("Air Range Limits are not V50-130 / H20-153kHz / 600 MHz")
    if base[126] != 1:
        fail("Air base extension count is not 1")

    noaudio = image[CTA_NOAUDIO:CTA_NOAUDIO + CTA_SIZE]
    audio = image[CTA_AUDIO:CTA_AUDIO + CTA_SIZE]
    for label, cta, want in (
        ("no-audio", noaudio, [*DTDS_1200, *DTDS_1080]),
        ("DP-audio", audio, list(DTDS_1080)),
    ):
        if sum(cta) & 0xFF:
            fail(f"mode1 {label} CTA checksum is not zero")
        if cta_vics(cta) != [4]:
            fail(f"mode1 {label} CTA VIC set is not [4] (720p60)")
        if cta_dtds(cta) != want:
            fail(f"mode1 {label} CTA DTD set mismatch")
    if (audio[3] >> 6) & 1 != 1:
        fail("DP-audio CTA does not advertise basic audio")
    if (noaudio[3] >> 6) & 1 != 0:
        fail("no-audio CTA advertises basic audio")
    # The mode 10/11 dispatcher reads its payload straight out of these offsets.
    if noaudio[24:42] != DTD_1200_90 or noaudio[42:60] != DTD_1200_120:
        fail("no-audio CTA dispatcher payload moved from offsets 24/42")


# --- 8051 emulation of the post-build base-DTD helper -------------------------
# The helper runs just before the EDID checksum is computed.  Executing it over
# every (E0BF, E0B9, E0BB) vector proves exactly which base DTD slots each
# logical mode writes -- the property this release is about.
BASE_HELPER_CODE = 0x91CC


def _signed(v: int) -> int:
    return v - 256 if v & 0x80 else v


def execute_base_helper(image: bytes, *, bf: int, b9: int, bb: int):
    xdata = {0xE0B9: b9 & 0xFF, 0xE0BB: bb & 0xFF, 0xE0BF: bf & 0xFF}
    pc, acc, carry, dptr = BASE_HELPER_CODE, 0, 0, 0
    regs, writes = [0] * 8, []

    def memcpy_rom() -> None:
        src = (regs[2] << 8) | regs[1]
        dst = (regs[4] << 8) | regs[0]
        length = (regs[6] << 8) | regs[7]
        if regs[5] != 1 or regs[3] != 0xFF:
            fail("memcpy ABI changed")
        for i in range(length):
            xdata[dst + i] = image[src + i + HDR]
            writes.append(dst + i)

    for _ in range(120):
        op = image[pc + HDR]
        if op == 0x90:
            dptr = int.from_bytes(image[pc + HDR + 1:pc + HDR + 3], "big"); pc += 3
        elif op == 0xE0:
            acc = xdata.get(dptr, 0); pc += 1
        elif op == 0xA3:
            dptr = (dptr + 1) & 0xFFFF; pc += 1
        elif op == 0xB4:
            imm, rel = image[pc + HDR + 1], _signed(image[pc + HDR + 2])
            carry = int(acc < imm)
            pc += 3 + (rel if acc != imm else 0)
        elif op == 0x70:
            rel = _signed(image[pc + HDR + 1]); pc += 2 + (rel if acc else 0)
        elif op == 0x14:
            acc = (acc - 1) & 0xFF; pc += 1
        elif op == 0xC3:
            carry = 0; pc += 1
        elif op == 0x94:
            v = acc - image[pc + HDR + 1] - carry
            carry, acc = int(v < 0), v & 0xFF
            pc += 2
        elif op == 0x50:
            rel = _signed(image[pc + HDR + 1]); pc += 2 + (rel if not carry else 0)
        elif op == 0x23:
            acc = ((acc << 1) | (acc >> 7)) & 0xFF; pc += 1
        elif op == 0x93:
            acc = image[((dptr + acc) & 0xFFFF) + HDR]; pc += 1
        elif 0x78 <= op <= 0x7F:
            regs[op - 0x78] = image[pc + HDR + 1]; pc += 2
        elif 0x08 <= op <= 0x0F:
            regs[op - 0x08] = (regs[op - 0x08] + 1) & 0xFF; pc += 1
        elif 0xE8 <= op <= 0xEF:
            acc = regs[op - 0xE8]; pc += 1
        elif 0xF8 <= op <= 0xFF:
            regs[op - 0xF8] = acc; pc += 1
        elif op == 0x12:
            target = int.from_bytes(image[pc + HDR + 1:pc + HDR + 3], "big")
            if target != 0x1795:
                fail(f"unexpected LCALL 0x{target:04X} in the base helper")
            memcpy_rom(); pc += 3
        elif op == 0x02:
            pc = int.from_bytes(image[pc + HDR + 1:pc + HDR + 3], "big")
        elif op == 0x22:
            return xdata, tuple(writes)
        else:
            fail(f"unsupported opcode 0x{op:02X} at code 0x{pc:04X}")
    fail("base helper emulation step limit exceeded")


MODE1_BF = 0x02
FIXED_RATE_DTD = {1: DTD_1200_72, 2: DTD_1200_90, 3: DTD_1200_120}


def expected_base_write(bf: int, b9: int, bb: int) -> tuple[int, bytes]:
    if bf == MODE1_BF:
        return SLOT0, b"".join(DTDS_1200)          # mode 1: 1200p60/90/120
    if bf == 0 and b9 == 0 and bb in FIXED_RATE_DTD:
        return SLOT0, FIXED_RATE_DTD[bb]           # mode 5/10/11: same-refresh 1200p
    return 0, b""


def verify_base_helper(image: bytes) -> int:
    vectors = 0
    for bf in range(256):
        for b9 in (0, 1, 2, 0xFF):
            for bb in (0, 1, 2, 3, 4, 0xFF):
                xdata, writes = execute_base_helper(image, bf=bf, b9=b9, bb=bb)
                start, payload = expected_base_write(bf, b9, bb)
                want = tuple(range(start, start + len(payload)))
                if writes != want:
                    fail(f"base DTD write set mismatch at BF=0x{bf:02X} B9={b9} BB={bb}: {writes!r}")
                if bytes(xdata[a] for a in want) != payload:
                    fail(f"base DTD payload mismatch at BF=0x{bf:02X} B9={b9} BB={bb}")
                if bf != MODE1_BF and any(SLOT1 <= a < SLOT1 + 18 for a in writes):
                    fail(f"BF=0x{bf:02X} writes base slot 1; the builder owns it")
                vectors += 1
    return vectors


# --- top level ---------------------------------------------------------------
def verify_stock(stock: bytes) -> None:
    validate_container(stock, "stock image")
    if sha256(stock) != STOCK_SHA256:
        fail("this is not the expected Air gen 1 stock 1140.\n"
             f"       expected SHA-256 {STOCK_SHA256}\n"
             f"       got             {sha256(stock)}")
    for label, offset, old, _new in RECORDS:
        if stock[offset:offset + len(old)] != old:
            fail(f"stock guard mismatch at 0x{offset:05X}: {label}")


def verify_output(stock: bytes, image: bytes) -> None:
    validate_container(image, "built image")
    if image != build(stock) or build(stock) != build(stock):
        fail("build is not deterministic")

    allowed = set(range(4)) | {TAG_OFF}
    for _label, offset, old, _new in RECORDS:
        allowed.update(range(offset, offset + len(old)))
    diffs = [i for i, (a, b) in enumerate(zip(stock, image)) if a != b]
    stray = [i for i in diffs if i not in allowed]
    if stray:
        fail("changed bytes outside the record set: " + " ".join(f"0x{i:05X}" for i in stray))
    if len(diffs) != EXPECTED_DIFFS:
        fail(f"changed-byte count is {len(diffs)}, expected {EXPECTED_DIFFS}")

    verify_edid(image)
    vectors = verify_base_helper(image)

    h = head(image)
    if sha256(image) != OUTPUT_SHA256:
        fail(f"output SHA-256 mismatch: {sha256(image)}")
    if h["stored_crc"] != OUTPUT_CRC:
        fail(f"container CRC mismatch: 0x{h['stored_crc']:08X}")
    if image[TAG_OFF] != OUTPUT_TAG:
        fail(f"bank0 tag mismatch: 0x{image[TAG_OFF]:02X}")

    print("=== XREAL Air gen 1 - DP bridge ===")
    print(f"  stock input     : SHA-256 verified, projectCode 0x{h['project']:04X} (air)")
    print(f"  records applied : {len(RECORDS)} ({RECORD_BYTES} bytes)")
    print(f"  changed bytes   : {len(diffs)} (records + CRC + bank0 tag)")
    print("  mode 1          : base 1200p60/90/120, CTA VIC4 + 1080p60/90/120")
    print("  mode 5/10/11    : base 1200p preferred + same-refresh 1080p, no CTA")
    print("  mode 3/4/9      : 3840x1200 @60/72/90 over HBR2, no CTA")
    print("  720p sources    : VIC 4 advertised; the bridge scales it to full screen")
    print("  EDID contract   : decoded and checked")
    print(f"  base helper     : {vectors} emulated vectors, all slots as specified")
    print(f"  container CRC   : 0x{h['stored_crc']:08X}")
    print(f"  bank0 tag       : 0x{image[TAG_OFF]:02X}")
    print(f"  sha256          : {sha256(image)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build the Air gen 1 DP bridge image from a stock 1140 container.",
        epilog="You must supply the stock firmware yourself. This tool does not "
               "download or contain any vendor firmware, and does not touch hardware.",
    )
    ap.add_argument("--src", type=Path, required=True,
                    metavar="STOCK_1140", help="path to the official Air gen 1 DP container")
    ap.add_argument("--out", type=Path, metavar="FILE", help="where to write the built image")
    ap.add_argument("--check-only", action="store_true",
                    help="build and verify in memory, write nothing")
    ap.add_argument("--verify", type=Path, metavar="FILE",
                    help="check that an existing file is byte-identical to the build")
    args = ap.parse_args()

    if not (args.out or args.check_only or args.verify):
        ap.error("choose one of --out, --check-only, --verify")

    stock = args.src.read_bytes()
    verify_stock(stock)
    image = build(stock)
    verify_output(stock, image)

    if args.verify:
        if not args.verify.exists() or args.verify.read_bytes() != image:
            fail(f"{args.verify} differs from the build or is missing")
        print(f"  verify          : {args.verify} [byte-identical]")
    elif args.check_only:
        print("  check-only      : nothing written")
    else:
        if args.out.resolve() == args.src.resolve():
            fail("refusing to overwrite the stock image")
        args.out.write_bytes(image)
        print(f"  wrote           : {args.out}")
    print("  hardware access : none")


if __name__ == "__main__":
    main()
