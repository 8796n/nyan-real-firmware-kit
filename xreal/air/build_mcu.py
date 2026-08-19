#!/usr/bin/env python3
"""Build the XREAL Air (gen 1) MCU image that pairs with the DP build.

WHAT THIS DOES
    Takes the official Air (gen 1) MCU container and applies 21 byte-level
    records.  Two features, both needed by the DP build:

    Panel follow.  The MCU drives the Sony micro-OLED panels, so it has to track
    the DP bridge: when the incoming signal is 1920x1200 the panels must be
    reconfigured for 1200 lines, and the panel timing group must match the
    refresh rate (60/72 Hz, 90 Hz and 120 Hz each need a different group).
    Without this the DP build alone produces a wrong or broken picture.

    Automatic DP audio.  Stock firmware only leaves USB audio, unless the user
    long-presses to switch manually or a genuine Nreal Adapter asserts the
    attention bit.  That is a problem for HDMI-to-USB-C converters and consoles,
    which carry no USB data at all: no USB audio is possible and there is nobody
    to press the button.  This build watches the USB SET_ADDRESS sticky word --
    if the host ever addresses the device it stays on USB audio for that power
    session, and only if the address stays zero for roughly five seconds does it
    enter the stock DP-audio transition.  It also restores the saved volume and
    locks the manual toggle for the rest of the session.

    Note that entering DP audio closes the USB composite device -- that is stock
    behaviour -- so HID control is unavailable while DP audio is active.

WHAT THIS DOES NOT DO
    It does not download, embed, or redistribute any vendor firmware, and it
    never touches hardware.  You supply the stock container yourself with
    ``--src``; the tool refuses anything whose SHA-256 is not the expected one.

    A bad MCU image can leave the application unable to boot.  Recovery is
    possible -- hold the button while connecting USB to reach the bootloader and
    write the stock image back -- but you need the stock file to do it, and the
    glasses cannot be read back.  Keep your copy.

VERIFICATION
      * the stock input must hash to STOCK_SHA256, with a valid container CRC
      * every record's "before" bytes must match before it is applied
      * the rebuild is deterministic and its SHA-256, container CRC and
        changed-byte count are pinned
      * nothing outside the record set may change

    Unlike the DP builder there is no EDID contract to decode here: this is ARM
    firmware driving panel SPI, and the honest guarantee is bit-exact
    reproduction of an image that was verified on hardware, not a behavioural
    model.  A mismatch anywhere is a hard failure.  There is no --force.

This file is self-contained: standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

# --- container ---------------------------------------------------------------
# 24-byte header, then an ARM Thumb payload.  The CRC-32 is stored big-endian at
# offset 0 and covers everything from offset 8 onwards.
HDR_LEN = 24
POLY = 0xF4ACFB13
VA_BIAS = 0xEFE8           # VA = file offset + VA_BIAS

SIZE = 153_888
STOCK_SHA256 = "B1784C6D618D3CF6F03D77A93442C3267A425CB2BE415E8912539E165645A3E7"
STOCK_CRC = 0x413F76A3
OUTPUT_SHA256 = "3842A4232356B993CFDE839B3D772EB861FC382B0506EF2098E1352F100A77FE"
OUTPUT_CRC = 0xE7B4FA4C
EXPECTED_DIFFS = 696       # bytes that actually change, including the header CRC

EXPECT_NAME = "Air.BootV_0.0.1"
EXPECT_LENGTH = 0x25918

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


def head(d: bytes) -> dict:
    return dict(
        stored_crc=struct.unpack_from(">I", d, 0)[0],
        length=struct.unpack_from("<I", d, 4)[0],
        name=d[8:HDR_LEN].split(b"\0")[0].decode("ascii", "replace"),
    )


def fix_container_crc(d: bytearray) -> int:
    crc = crc_container(bytes(d[8:8 + head(bytes(d))["length"]]))
    struct.pack_into(">I", d, 0, crc)
    return crc


def validate_container(d: bytes, what: str) -> None:
    if len(d) != SIZE:
        fail(f"{what}: expected {SIZE} bytes, got {len(d)}")
    h = head(d)
    if h["name"] != EXPECT_NAME or h["length"] != EXPECT_LENGTH:
        fail(f"{what}: not an Air gen 1 MCU container ({h['name']!r}, len 0x{h['length']:X})")
    if crc_container(d[8:8 + h["length"]]) != h["stored_crc"]:
        fail(f"{what}: container CRC-32 does not match its header")
    # ARM vector table sanity: initial SP in SRAM, reset vector inside the payload.
    sp, reset = struct.unpack_from("<II", d, HDR_LEN)
    if not 0x20000000 <= sp < 0x20040000:
        fail(f"{what}: initial stack pointer 0x{sp:08X} is not in SRAM")
    reset_file = (reset & ~1) - VA_BIAS
    if not HDR_LEN <= reset_file < SIZE:
        fail(f"{what}: reset vector 0x{reset:08X} falls outside the payload")


# --- the change set ----------------------------------------------------------
# Offsets are file offsets in the container; VA = offset + 0xEFE8.  Records are
# grouped by the work that introduced them:
#
#   panel row-count follow  the panels must switch to 1200 lines when the input
#                           does; this is what makes the DP build usable
#   panel timing group      60/72 Hz, 90 Hz and 120 Hz need different panel
#                           timing groups; mode 9 needed the 90 Hz group
#   mode 10 cold recovery   re-converge after a cold start or DP reset
#   DP audio / volume       routing, local volume and session lock behaviour
#                           carried over from the same research line
#
# Every record is a verbatim before/after pair, so the whole change set can be
# audited by diffing this table against the two images.

RECORDS: tuple[Record, ...] = (
    ("panel init: dual-panel row-count follow (VA 0x1244B..)",
     0x0034CB,
     bytes.fromhex("48007800b938bd01f09bff00909df800000a21b1eb101f03d000202c490870f1e79df8000000f0010050b10020274908709df80000c0f3400010b10120244908702348007800283ed0"),
     bytes.fromhex("4d2c78a62c1fd201f09bff0346d80718d518090a2815d1e81de130006878b9980707d401342c70a62c0dd301f0defa30b90fe0012026490870a820287004e0a92000e00020287038bd")),
    ("panel init: helper call re-target",
     0x00351E,
     bytes.fromhex("07f049fc"),
     bytes.fromhex("0df05ab9")),
    ("panel init: helper call re-target",
     0x00355E,
     bytes.fromhex("02f045fb"),
     bytes.fromhex("0df0c9f8")),
    ("panel init: helper call re-target",
     0x003590,
     bytes.fromhex("00bf00bf9c"),
     bytes.fromhex("0df09ef8bd")),
    ("DP-audio / USB address routing hook",
     0x004D3C,
     bytes.fromhex("06f086f9"),
     bytes.fromhex("0bf023fd")),
    ("periodic hook A (VA 0x13F5A): read E086 and re-apply panel rows",
     0x004F72,
     bytes.fromhex("7e48807a00b970bd00f0be"),
     bytes.fromhex("05f031fe00b970bd0af0f5")),
    ("periodic hook B (VA 0x13FA8): same, second call site",
     0x004FC0,
     bytes.fromhex("00f09b"),
     bytes.fromhex("0af0d2")),
    ("auto 2D arm: logical mode + panel group",
     0x005042,
     bytes.fromhex("38b301200ff001fd"),
     bytes.fromhex("00bf012011f027fb")),
    ("auto 2D arm: hold logical mode 1 for the 72 Hz arm",
     0x0050A4,
     bytes.fromhex("05"),
     bytes.fromhex("01")),
    ("auto 2D arm: 72 Hz group via ensure_group",
     0x0050AE,
     bytes.fromhex("b8b101200ff0cbfc"),
     bytes.fromhex("00bf012011f0f1fa")),
    ("auto 2D arm: hold logical mode 1 for the 90 Hz arm",
     0x0050EE,
     bytes.fromhex("0a"),
     bytes.fromhex("01")),
    ("auto 2D arm: 90 Hz group via ensure_group",
     0x0050F8,
     bytes.fromhex("c0b101200ff0a6fc"),
     bytes.fromhex("00bf022011f0ccfa")),
    ("auto 2D arm: hold logical mode 1 for the 120 Hz arm",
     0x00513A,
     bytes.fromhex("0b"),
     bytes.fromhex("01")),
    ("auto 2D arm: 120 Hz group via ensure_group",
     0x005144,
     bytes.fromhex("40b903200ff080fc"),
     bytes.fromhex("00bf032011f0a6fa")),
    ("3D arm: panel group selection",
     0x005772,
     bytes.fromhex("012802d001"),
     bytes.fromhex("022802d002")),
    ("mode 9 (3D SBS 90 Hz): panel group 1 -> group 2 (5L2_90)",
     0x0057D0,
     bytes.fromhex("012802d001"),
     bytes.fromhex("022802d002")),
    ("mode 10 cold recovery: read actual DP BF before the cache gate",
     0x00ABD8,
     bytes.fromhex("f8b507460d461446012269463846fff722ff06466eb90098a043009005ea040000990843009001226946384600f003f806463046f8bd"),
     bytes.fromhex("10b50a4844780a2c09d00948807a50b9052c01d00b2c04d104f0bafc01e00bf037fd002010bd012010bd00bf8a1300203603002000bf")),
    ("panel row-count helper (VA 0x1E51E): 1200/1080 pair selection",
     0x00F536,
     bytes.fromhex("2de9f84306460c464ff001080027002000900220fbf727fa05460122694644f2a200f6f73cfd9df80000aa2803d000202080804613e09df80000aa280fd10222294644f2a300f6f72afd2f883a46314644f2a500f6f723fd27804ff000082846fbf7adf94046bde8f883"),
     bytes.fromhex("30b504460d462078a5280fd16178ff20f6f719fba078f5f778ff2070e021ff20f6f711fb01202880002030bd0020288030bd70b5f5f7c6ff0446022c03d100240025d42601e001255c26452007f041fbb04207d029463f2001f0ecf83146452001f0e8f8204670bd00bf")),
    ("panel pair writer (VA 0x1F6B4): left/right 0x3F and 0x45 with commit guard",
     0x0106CC,
     bytes.fromhex("2de9f84304460d464ff001080027002000900220faf75cf906460122694640f22470f5f771fc9df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f22570f5f75cfc37883a46214640f22770f5f755fc2f804ff000083046faf7dff84046bde8f8832de9f84304460d464ff001080027002000900220faf724f90646012269464ff4ea60f5f739fc9df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f25170f5f724fc37883a46214640f25370f5f71dfc2f804ff000083046faf7a7f84046bde8f8832de9f84304460d464ff001080027002000900220faf7ecf806460122694640f27c70f5f701fc9df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f27d70f5f7ecfb37883a46214640f27f70f5f7e5fb2f804ff000083046faf76ff84046bde8f883"),
     bytes.fromhex("c6e700bf10b513480078a7280bd11248c08801f0d1fa082010490a7802430a70ae390120087010bd10b5f5f779fa09480078a7280cd10848c078c12808d108480849097830f811000349c88001f0b4fa10bd00bf040200208a130020e6120020bc120020dc12002000bf00bf00bf00bf70b504460d462078a5280dd16178a078002902d0f9f768f801e0fef781fe207001202880002070bd0020288070bd70b504460d462a4621460120fbf712fb2a4621460020fbf70dfb70bd10b5faf760fce01e012801d9092c0cd100213f20fff7e6ffd4214520fff7e2ff10bd00bf00bf56e700bf012c05d0052c03d00a2c01d00b2c01d1fef7d2fe10bd10b504f040f9fef7ccfe10bd00bf00bf0d490878a62811d1a720087000200a49086001200a4908700a490a78082002430a70ae3901200870f2f7aebefaf7d7faf2f790be00bf040200209403002032120020e6120020")),
    ("ensure_group helper (VA 0x25650): compare cached group, apply only on change",
     0x016668,
     bytes.fromhex("38b5044600bf002000906846fff7a2ff054640f2ff21009890fbf1f06421484340f2ff22009991fbf2f1c1f101015023009a92fbf3f2514301eb810100eb41002060284638bd"),
     bytes.fromhex("10b5eef735fe002803d1f8f779ff002010bd06480121417041730a20eef75cff0a24faf77cf8002010bd00bf8a1300200349497b814201d0faf791b8704700bf8a13002000bf")),
    ("panel group setter entry (VA 0x25BF0)",
     0x016C08,
     bytes.fromhex("f0b5044600200ae011f8016b054d2b685d1c044f3d60044d2d68ee54401c9042f2d3f0bd"),
     bytes.fromhex("10b53f20f8f726fca84206d14520f8f721fcb04201d1304610bd002010bd00bf00bf00bf")),
)

RECORD_BYTES = sum(len(old) for _l, _o, old, _n in RECORDS)


def build(stock: bytes) -> bytes:
    out = bytearray(stock)
    for label, offset, old, new in RECORDS:
        if out[offset:offset + len(old)] != old:
            fail(f"stock image does not match record at 0x{offset:06X}: {label}")
        out[offset:offset + len(new)] = new
    fix_container_crc(out)
    return bytes(out)


def verify_stock(stock: bytes) -> None:
    validate_container(stock, "stock image")
    if sha256(stock) != STOCK_SHA256:
        fail("this is not the expected Air gen 1 stock MCU image.\n"
             f"       expected SHA-256 {STOCK_SHA256}\n"
             f"       got             {sha256(stock)}")
    if head(stock)["stored_crc"] != STOCK_CRC:
        fail(f"stock container CRC is 0x{head(stock)['stored_crc']:08X}, expected 0x{STOCK_CRC:08X}")
    for label, offset, old, _new in RECORDS:
        if stock[offset:offset + len(old)] != old:
            fail(f"stock guard mismatch at 0x{offset:06X}: {label}")


def verify_output(stock: bytes, image: bytes) -> None:
    validate_container(image, "built image")
    if image != build(stock) or build(stock) != build(stock):
        fail("build is not deterministic")

    allowed = set(range(4))
    for _label, offset, old, _new in RECORDS:
        allowed.update(range(offset, offset + len(old)))
    diffs = [i for i, (a, b) in enumerate(zip(stock, image)) if a != b]
    stray = [i for i in diffs if i not in allowed]
    if stray:
        fail("changed bytes outside the record set: " + " ".join(f"0x{i:06X}" for i in stray))
    if len(diffs) != EXPECTED_DIFFS:
        fail(f"changed-byte count is {len(diffs)}, expected {EXPECTED_DIFFS}")

    h = head(image)
    if sha256(image) != OUTPUT_SHA256:
        fail(f"output SHA-256 mismatch: {sha256(image)}")
    if h["stored_crc"] != OUTPUT_CRC:
        fail(f"container CRC mismatch: 0x{h['stored_crc']:08X}")

    print("=== XREAL Air gen 1 - MCU ===")
    print("  stock input     : SHA-256 and container CRC verified")
    print(f"  records applied : {len(RECORDS)} ({RECORD_BYTES} bytes)")
    print(f"  changed bytes   : {len(diffs)} (records + header CRC)")
    print("  panel rows      : follows the input class, 1080 <-> 1200")
    print("  panel groups    : 60/72 Hz, 90 Hz and 120 Hz, mode 9 included")
    print("  DP audio        : automatic when the host carries no USB data (~5 s)")
    print("  volume          : saved level restored on the audio transition")
    print(f"  container CRC   : 0x{h['stored_crc']:08X}")
    print(f"  sha256          : {sha256(image)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build the Air gen 1 MCU image that pairs with the 1920x1200 DP build.",
        epilog="You must supply the stock firmware yourself. This tool does not "
               "download or contain any vendor firmware, and does not touch hardware.",
    )
    ap.add_argument("--src", type=Path, required=True, metavar="STOCK_MCU",
                    help="path to the official Air gen 1 MCU container")
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
