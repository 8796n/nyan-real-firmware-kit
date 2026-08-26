#!/usr/bin/env python3
"""Build the XREAL Air (gen 1) MCU image that pairs with the DP build.

WHAT THIS DOES
    Takes the official Air (gen 1) MCU container and applies guarded byte-level
    records.  The main features are:

    Panel follow.  The MCU drives the Sony micro-OLED panels, so it has to track
    the DP bridge: when the incoming signal is 1920x1200 the panels must be
    reconfigured for 1200 lines, and the panel timing group must match the
    refresh rate (60/72 Hz, 90 Hz and 120 Hz each need a different group).
    Without this the DP build alone produces a wrong or broken picture.

    Automatic RGB/scaler link.  The paired DP publishes a complemented timing
    tag.  Native 1080p/1200p at 60/72/90/120 Hz and Full-SBS at 60/72/90 Hz
    use the 58/03 four-lane RGB panel link.  True 720p alone keeps the official
    D9/04 scaler/YUV link and uses panel group 2; native 60 Hz remains on group
    1.  Unknown, torn or stale states hold the current link.
    In adaptive mode, native input keeps external C0=0 while the panel remains
    RGB, avoiding a second cold retraining.  Fixed-rate and Full-SBS modes keep
    their existing C0=2 policy.

    Automatic DP audio.  Stock firmware only leaves USB audio, unless the user
    long-presses to switch manually or a genuine Nreal Adapter asserts the
    attention bit.  The tested HDMI-to-USB-C converter path carries no USB data,
    so USB audio is impossible and there is nobody to press the button.  This
    build watches the USB SET_ADDRESS sticky word: if a host addresses the
    device during the initial wait state, the automatic path leaves USB audio
    active for that power session.  Only while the stock audio state remains at
    that wait state and the address stays zero for roughly five seconds does it
    take the full DP-audio transition.  It selects the LPCM-capable EDID, asks
    the source to re-read it through B6/HPD, repeats B6 after a guarded delay,
    restores the saved gain, then opens the DP-I2S/SmartPA route.  The roughly
    five-second no-USB grace period is followed by a visible re-enumeration
    blackout; directly connected USB hosts stay on USB audio.

    Powered HDMI-converter hotplug recovery.  A measured connected-but-broken
    DP tuple is required for 75 consecutive observations before B6 is toggled
    once.  The action latches until the tuple changes, so a normal or transient
    state cannot cause repeated retraining.

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
OUTPUT_SHA256 = "F292B1245F2F26E209D6DACA6ADF50A58534B4EAEDC48C4FC8705703C879223D"
OUTPUT_CRC = 0x511524B3
PAIRED_DP_SHA256 = "34AEE893AC697D314CB522D135AAE8C9222CC9461B62C096C616FEF44DE87AD8"
EXPECTED_DIFFS = 1543      # bytes that actually change, including the header CRC

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
    ("first-eye automatic RGB/scaler policy hook",
     0x004F72,
     bytes.fromhex("05f031fe"),
     bytes.fromhex("19f041fc")),
    ("periodic automatic RGB/scaler monitor hook",
     0x00B39C,
     bytes.fromhex("00bf00bf"),
     bytes.fromhex("13f024f9")),
    ("checked DP reader call site",
     0x00F59A,
     bytes.fromhex("2046"),
     bytes.fromhex("0020")),
    ("checked DP reader and both-eye link writers",
     0x01065C,
     bytes.fromhex("2de9f84304460d464ff001080027002000900220faf794f90646012269464ff4df60f5f7a9fc9df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f2f960f5f794fc37883a46"),
     bytes.fromhex("70b504460d462078a62820d1607852281dd1a07847281ad1e678ff2e11d0002e01d0022e13d1d921022e00d15821032000f06df80421022e00d10321042000f066f8a620207001202880002070bd0020288070bd")),
    ("automatic policy support helpers",
     0x01E598,
     bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     bytes.fromhex("70b584b004460d4600260396012d01d0022d17d1e021ff20e7f7e4fa002811d14ff47a70012103aa0b46009201950290224643210548e9f7dbfc002802d10398012101e00020002104b070bd00100840")),
    ("automatic RGB/scaler policy",
     0x01E5E8,
      bytes(568),
     bytes.fromhex("f8b5012802d0022800d0ffe000900026864f8e200221fff7cbff012900d0c1e0044686200221fff7c3ff012900d0b9e005468e200221fff7bbff012900d0b1e0a04200d0aee0e0b2210a4840ff2800d0a8e0e0b22a0a01460f231940914200d0a0e0032a00d99de07979914200d099e00146f0231940a02904d0b0292cd0c0293dd08fe0e8b2002800d08be03879002800d087e066494878012817d0b97a002900d07fe02a0a012a04d0022a06d0032a08d077e0052800d074e00be00a2800d070e007e00b2800d06ce003e0b97a022900d067e0022666e0e8b2012800d061e03879002800d05de0b87a022800d059e04f494878012800d054e0002653e0e8b2022800d04ee03879002802d001282ad048e0e8b2022800d044e03879002800d040e043494878012817d0b97a002900d038e02a0a012a04d0022a06d0032a08d030e0052800d02de00be00a2800d029e007e00b2800d025e003e0b97a022900d020e002261fe03879012800d01ae0b87a002800d016e02e4948782a0a002a04d0012a06d0022a08d00ce0032800d009e006e0042800d005e002e0092800d001e0022600e032e0c0200121fff701ff012900d014e0f97ab14200d010e0b04200d00de0009b012b0dd00420f0f753fe022e02d004281ad005e0032817d002e0fe7200f020f882200021f1f7cbff022e01d0d92100e058210320f1f7c3ff022e01d0042100e003210420f1f7bbfff8bd00bf10b5ecf7edf904460220fff7f1fe204610bd00bf70b5034de5f7e9fc360300208a13002094030020")),
    ("automatic no-USB entry -> full DP-audio transition",
     0x00351E,
     bytes.fromhex("0df05ab9"),
     bytes.fromhex("07f049fc")),
    ("manual/adapter entry -> deferred full DP-audio transition",
     0x00355E,
     bytes.fromhex("0df0c9f8"),
     bytes.fromhex("0df03af9")),
    ("full DP-audio second-B6, saved-gain/deferred-route and manual recovery helpers",
     0x01065C,
     bytes.fromhex("70b504460d462078a62820d1607852281dd1a07847281ad1e678ff2e11d0002e01d0022e13d1d921022e00d15821032000f06df80421022e00d10321042000f066f8a620207001202880002070bd0020288070bd214640f2fb60f5f78dfc2f804ff000083046faf717f94046bde8f883c6e700bf10b513480078a7280bd11248c08801f0d1fa082010490a7802430a70ae390120087010bd10b5f5f779fa09480078a7280cd10848c078c12808d108480849097830f811000349c88001f0b4fa10bd00bf040200208a130020e6120020bc120020dc12002000bf00bf00bf00bf70b504460d462078a5280dd16178a078002902d0f9f768f801e0fef781fe207001202880002070bd0020288070bd70b504460d462a4621460120fbf712fb2a4621460020fbf70dfb70bd10b5faf760fce01e012801d9092c0cd100213f20fff7e6ffd4214520fff7e2ff10bd00bf00bf56e700bf012c05d0052c03d00a2c01d00b2c01d1fef7d2fe10bd10b504f040f9fef7ccfe10bd00bf00bf0d490878a62811d1a720087000200a49086001200a4908700a490a78082002430a70ae3901200870f2f7aebefaf7d7faf2f790be00bf040200209403002032120020e6120020"),
     bytes.fromhex("70b504460d462078a62823d1607852281dd1a07847281ad1e678ff2e11d0002e01d0022e13d1d921022e00d15821032000f06df80421022e00d10321042000f066f8a620207001202880002070bd0020288070bd2078b628f9d16078a528f6d11549c87901214840f4f7d4fee9e700bfc6e700bf10b50f4c2078a62818d1a72020704ff47a7006f046fd0b49c87901214840f4f7bffe4ff47a7006f03cfd0748c08801f0c1fa082005490a78024309e010bd00bf04020020360300208a130020e61200200a70ae390120087010bd2f804ff000083046faf7dff84046bde8f88370b504460d462078a5280dd16178a078002902d0f9f768f801e0fef781fe207001202880002070bd0020288070bd70b504460d462a4621460120fbf712fb2a4621460020fbf70dfb70bd10b5faf760fce01e012801d9092c0cd100213f20fff7e6ffd4214520fff7e2ff10bd00bf00bf56e700bf012c05d0052c03d00a2c01d00b2c01d1fef7d2fe10bd10b504f040f9fef7ccfe10bd00bf00bf10b50b480078a62810d14ff47a7006f0c5fc08480949097830f811000849c88001f03dfa0648c08801f041faf5f7f3f910bd04020020bc120020dc1200208a13002000bf00bf")),
    ("adaptive-mode external-C0 separation hook",
     0x01E78E,
     bytes.fromhex("c0200121"),
     bytes.fromhex("00f047b8")),
    ("external-C0 shadow comparison uses separated expectation",
     0x01E79E,
     bytes.fromhex("b142"),
     bytes.fromhex("a142")),
    ("external-C0 actual comparison uses separated expectation",
     0x01E7A4,
     bytes.fromhex("b042"),
     bytes.fromhex("a042")),
    ("external-C0 recovery stores separated expectation",
     0x01E7C6,
     bytes.fromhex("fe72"),
     bytes.fromhex("fc72")),
    ("periodic gate -> latched powered-hotplug recovery",
     0x01E7FA,
     bytes.fromhex("ecf7edf9"),
     bytes.fromhex("00f01ff8")),
    ("adaptive-mode external-C0 separation helper",
     0x01E820,
     bytes(28),
     bytes.fromhex("344605484078012800d10024c0200121fff7b2fefff7afbf8a130020")),
    ("latched exact-tuple powered-hotplug recovery helper",
     0x01E83C,
     bytes(192),
     bytes.fromhex("10b5194ce6f75bfe002828d18820e6f7f9fd052823d18920e6f7f4fd00281ed19020e6f7effd0b2819d18e20e6f7eafd002814d18f20e6f7e5fd00280fd12078ff280ed0013020704b280ad1ff2020700649c87901214840e6f7ecfd01e000202070ecf79bf910bd3a1200203603002000bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf")),
    ("true-720 accepted branch -> panel-group-2 helper",
     0x01E6E2,
     bytes.fromhex("002653e0"),
     bytes.fromhex("00f0efb8")),
    ("true-720-only cache-aware panel-group-2 helper",
     0x01E8C4,
     bytes.fromhex("00bf00bf00bf00bf00bf00bf"),
     bytes.fromhex("0220f7f7e7fe0026fff75fbf")),
)

RECORD_BYTES = sum(len(old) for _l, _o, old, _n in RECORDS)


def build(stock: bytes) -> bytes:
    out = bytearray(stock)
    for label, offset, old, new in RECORDS:
        if out[offset:offset + len(old)] != old:
            fail(f"record precondition does not match at 0x{offset:06X}: {label}")
        out[offset:offset + len(new)] = new
    fix_container_crc(out)
    return bytes(out)


def classify_panel_link(
    tag_pair: int,
    raw_pair: int,
    *,
    b9: int,
    bf: int,
    shadow_refresh: int,
    mode: int,
    reads_ok: bool = True,
) -> tuple[bool, int | None]:
    """Model the policy as (valid, desired C0); invalid states hold the link."""
    tag = tag_pair & 0xFF
    complement = tag_pair >> 8
    raw_class = raw_pair & 0xFF
    refresh = raw_pair >> 8
    if not (
        reads_ok
        and tag ^ complement == 0xFF
        and refresh in range(4)
        and shadow_refresh == refresh
        and tag & 0x0F == refresh
    ):
        return False, None
    family = tag & 0xF0
    adaptive_2d = mode == 1 and bf == 2
    fixed_2d = bf == 0 and mode == {1: 5, 2: 10, 3: 11}.get(refresh)
    if family == 0xA0 and raw_class == 0 and b9 == 0 and (adaptive_2d or fixed_2d):
        return True, 2
    if family == 0xB0 and raw_class == 1 and b9 == 0 and adaptive_2d:
        return True, 0
    if family == 0xC0 and raw_class == 2 and b9 == 0 and (adaptive_2d or fixed_2d):
        return True, 2
    if (
        family == 0xC0
        and raw_class == 2
        and b9 == 1
        and bf == 0
        and mode == {0: 3, 1: 4, 2: 9}.get(refresh)
    ):
        return True, 2
    return False, None


def verify_panel_link_policy() -> int:
    accepted: set[tuple[str, int]] = set()
    for label, family, raw_class in (("1080p", 0xA0, 0), ("720p", 0xB0, 1), ("1200p", 0xC0, 2)):
        for refresh in range(4):
            tag = family | refresh
            got = classify_panel_link(
                tag | ((tag ^ 0xFF) << 8), raw_class | (refresh << 8),
                b9=0, bf=2, shadow_refresh=refresh, mode=1,
            )
            if got != (True, 0 if family == 0xB0 else 2):
                fail(f"{label} refresh {refresh} panel-link policy mismatch")
            accepted.add((label, refresh))
    for label, family, raw_class in (("1080p-fixed", 0xA0, 0), ("1200p-fixed", 0xC0, 2)):
        for refresh, mode in ((1, 5), (2, 10), (3, 11)):
            tag = family | refresh
            if classify_panel_link(
                tag | ((tag ^ 0xFF) << 8), raw_class | (refresh << 8),
                b9=0, bf=0, shadow_refresh=refresh, mode=mode,
            ) != (True, 2):
                fail(f"{label} refresh {refresh} panel-link policy mismatch")
            accepted.add((label, refresh))
    for refresh, mode in ((0, 3), (1, 4), (2, 9)):
        tag = 0xC0 | refresh
        if classify_panel_link(
            tag | ((tag ^ 0xFF) << 8), 2 | (refresh << 8),
            b9=1, bf=0, shadow_refresh=refresh, mode=mode,
        ) != (True, 2):
            fail(f"Full-SBS refresh {refresh} panel-link policy mismatch")
        accepted.add(("SBS", refresh))
    if len(accepted) != 21:
        fail(f"panel-link policy accepts {len(accepted)} canonical cells, expected 21")
    if classify_panel_link(0x5FA1, 0x0100, b9=0, bf=2, shadow_refresh=1, mode=1) != (False, None):
        fail("corrupt timing tag did not hold the current link")
    return len(accepted)


def expected_external_c0(mode: int, panel_link: int) -> int:
    """Adaptive mode keeps external C0=0 while the panel link follows input."""
    return 0 if mode == 1 else panel_link


HOTPLUG_MATCH_COUNT = 75
HOTPLUG_LATCHED = 0xFF
BROKEN_HOTPLUG_TUPLE = (0x00, 0x05, 0x00, 0x0B, 0x00, 0x00)


def is_broken_hotplug_tuple(values: tuple[int, int, int, int, int, int]) -> bool:
    return values == BROKEN_HOTPLUG_TUPLE


def hotplug_recovery_step(counter: int, broken: bool) -> tuple[int, bool]:
    """Model one observation as (new counter/latch, toggle B6 once)."""
    if not broken:
        return 0, False
    if counter == HOTPLUG_LATCHED:
        return HOTPLUG_LATCHED, False
    counter = (counter + 1) & 0xFF
    if counter == HOTPLUG_MATCH_COUNT:
        return HOTPLUG_LATCHED, True
    return counter, False


def route_panel_group(input_class: int, refresh_class: int, normal_group: int) -> int:
    """Override only the accepted true-720p60 route with panel group 2."""
    return 2 if (input_class, refresh_class) == (1, 0) else normal_group


def verify_release_policies(image: bytes) -> None:
    for mode, panel_link, wanted in ((1, 2, 0), (1, 0, 0), (10, 2, 2), (9, 2, 2)):
        if expected_external_c0(mode, panel_link) != wanted:
            fail(f"external-C0 separation model failed for mode {mode}, link {panel_link}")

    if not is_broken_hotplug_tuple(BROKEN_HOTPLUG_TUPLE):
        fail("powered-hotplug broken tuple model changed")
    if is_broken_hotplug_tuple((0, 5, 0, 11, 0, 1)):
        fail("powered-hotplug tuple accepted a nonzero complement byte")

    counter = 0
    for _ in range(HOTPLUG_MATCH_COUNT - 1):
        counter, toggle = hotplug_recovery_step(counter, True)
        if toggle:
            fail("powered-hotplug recovery toggled B6 before its threshold")
    counter, toggle = hotplug_recovery_step(counter, True)
    if (counter, toggle) != (HOTPLUG_LATCHED, True):
        fail("powered-hotplug recovery did not latch and toggle at its threshold")
    if hotplug_recovery_step(counter, True) != (HOTPLUG_LATCHED, False):
        fail("powered-hotplug recovery retriggered while latched")
    if hotplug_recovery_step(counter, False) != (0, False):
        fail("powered-hotplug latch did not clear after tuple recovery")

    if route_panel_group(1, 0, 1) != 2:
        fail("true-720p60 no longer selects panel group 2")
    if route_panel_group(2, 0, 1) != 1 or route_panel_group(0, 0, 1) != 1:
        fail("native 60-Hz input no longer retains panel group 1")
    if image[0x01E6E2:0x01E6E6] != bytes.fromhex("00f0efb8"):
        fail("true-720 panel-group hook changed")
    if image[0x01E8C4:0x01E8D0] != bytes.fromhex("0220f7f7e7fe0026fff75fbf"):
        fail("true-720 panel-group helper changed")


def verify_stock(stock: bytes) -> None:
    validate_container(stock, "stock image")
    if sha256(stock) != STOCK_SHA256:
        fail("this is not the expected Air gen 1 stock MCU image.\n"
             f"       expected SHA-256 {STOCK_SHA256}\n"
             f"       got             {sha256(stock)}")
    if head(stock)["stored_crc"] != STOCK_CRC:
        fail(f"stock container CRC is 0x{head(stock)['stored_crc']:08X}, expected 0x{STOCK_CRC:08X}")
    probe = bytearray(stock)
    for label, offset, old, new in RECORDS:
        if probe[offset:offset + len(old)] != old:
            fail(f"record guard mismatch at 0x{offset:06X}: {label}")
        probe[offset:offset + len(new)] = new


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

    policy_cells = verify_panel_link_policy()
    verify_release_policies(image)

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
    print("  panel groups    : native 60/72, 90, 120; true 720p uses group 2 only")
    print("  native/SBS panel: 58/03 four-lane RGB; adaptive mode keeps external C0=0")
    print("  true 720p panel : official D9/04 scaler/YUV; external C0=0")
    print(f"  link policy     : {policy_cells} canonical cells; transients hold current link")
    print("  DP audio        : full EDID/B6 transition after ~5 s without USB data")
    print("  volume          : saved level restored on the audio transition")
    print(f"  HDMI hotplug    : exact broken tuple x {HOTPLUG_MATCH_COUNT}; one latched B6 toggle")
    print(f"  container CRC   : 0x{h['stored_crc']:08X}")
    print(f"  sha256          : {sha256(image)}")
    print(f"  paired DP       : {PAIRED_DP_SHA256}")


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
