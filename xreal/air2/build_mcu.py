#!/usr/bin/env python3
"""Build the XREAL Air 2 / Air 2 Pro MCU image from official firmware.

Relative to the official image, this build automatically performs the official
full DP-audio transition when USB data is absent, including the audio EDID/HPD
re-enumeration and saved-volume restore. It also keeps mode changes consistent
across native RGB and true 720p YCbCr input. Native 1080p selects the four-lane
RGB panel table, 120 Hz selects its matching timing table, and 720p selects the
official scaler/YUV table. Mode 1 clears the mode-9-only state before returning
to normal 2D. Initial setup and mode 1 reuse the official full-register apply
and OLED close/open lifecycle. On the tested powered HDMI converter, each exact
720p disconnect edge toggles live B6 once; reconnect is left to the converter's
delayed retrain.

The tool is offline and standard-library only.  It accepts one known official
Air 2-family MCU container, applies guarded records and pins the complete output.  It
never downloads firmware or touches hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


POLY = 0xF4ACFB13
HDR_LEN = 0x40

SIZE = 151_160
STOCK_SHA256 = "C07633E97215346468A18F5306A10F800388A80CCD7DCFE800D468F4AB1BFD49"
STOCK_CRC = 0x169B7EE4
OUTPUT_SHA256 = "950CA9535AFBD02C40D97A167DB06ECFAEEBC35F6ADCCDED81829CC44A8BE4C9"
OUTPUT_CRC = 0xCFB740BE
EXPECTED_DIFFS = 526

EXPECT_LENGTH = 0x24E70
EXPECT_PROJECT = 0x0900
EXPECT_IMAGE_TYPE = 1
EXPECT_VERSION = b"09.1.00.180_20240507"

Record = tuple[str, int, bytes, bytes]

FULL_TRANSITION_HOOK_OFFSET = 0x03196
FULL_TRANSITION_HOOK = bytes.fromhex("07 F0 17 FF")  # BL official OLED close
FULL_TRANSITION_HELPER_OFFSET = 0x0FD00
# Wait 2000 ms after the stock 1000 ms delay, then issue the second B6.
FULL_TRANSITION_HELPER = bytes.fromhex(
    "10 B5 0C 4C 20 78 A6 28 13 D1 A7 20 20 70 40 F2 D0 70 "
    "06 F0 92 FE 08 49 C8 79 01 21 48 40 F5 F7 A9 FA 4F F4 "
    "7A 70 06 F0 88 FE 04 48 C0 88 00 F0 07 F8 10 BD 48 02 "
    "00 20 7A 03 00 20 4C 0E 00 20 10 B5 01 F0 C1 FA 08 20 "
    "02 49 0A 78 02 43 0A 70 10 BD 00 BF 92 0D 00 20"
)


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def hx(text: str) -> bytes:
    return bytes.fromhex(text)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def crc_container(data: bytes) -> int:
    """CRC-32 / poly 0xF4ACFB13 / MSB-first / init 0 / xorout 0."""
    c = 0
    for b in data:
        c ^= b << 24
        for _ in range(8):
            c = ((c << 1) ^ POLY) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c


def head(data: bytes) -> dict:
    stored_crc, length, project, image_type = struct.unpack_from("<4I", data, 0)
    return dict(
        stored_crc=stored_crc,
        length=length,
        project=project,
        image_type=image_type,
        version=data[0x10:0x24],
    )


def fix_container_crc(data: bytearray) -> int:
    crc = crc_container(bytes(data[8:]))
    struct.pack_into("<I", data, 0, crc)
    return crc


def validate_container(data: bytes, what: str) -> None:
    if len(data) != SIZE:
        fail(f"{what}: expected {SIZE} bytes, got {len(data)}")
    h = head(data)
    if h["length"] != EXPECT_LENGTH or h["length"] + 8 != len(data):
        fail(f"{what}: declared length does not match the Air 2 MCU container")
    if h["project"] != EXPECT_PROJECT or h["image_type"] != EXPECT_IMAGE_TYPE:
        fail(f"{what}: project/image type mismatch (0x{h['project']:04X} / {h['image_type']})")
    if h["version"] != EXPECT_VERSION:
        fail(f"{what}: version mismatch ({h['version']!r})")
    if crc_container(data[8:]) != h["stored_crc"]:
        fail(f"{what}: container CRC-32 does not match its header")
    initial_sp, reset = struct.unpack_from("<II", data, HDR_LEN)
    if not 0x20000000 <= initial_sp < 0x20040000:
        fail(f"{what}: initial stack pointer 0x{initial_sp:08X} is not in SRAM")
    if not 0x0000F000 <= (reset & ~1) < 0x00040000:
        fail(f"{what}: reset vector 0x{reset:08X} is outside the application range")


RECORDS: tuple[Record, ...] = (
    ("no-USB official full DP-audio transition policy", 0x0313E,
     hx("002038b53448007800b938bd02f061f800909df800000a21b1eb101f03d000202d490870f1e79df8000000f0010050b10020284908709df80000c0f3400010b101202549087024480078002840d001f00bfb0446012c1fd007f017ff02e00a2013f04cfc1e4800680528f8d300201b49086001201b490870002001f0e6fe012001f001fb1849c979012901d0012100e00021084602f04ff802f039fcfef713fe0a2013f02bfc02f044fc0f481049097830f811000f49c8804ff47a7013f01efc0c49c8880ef09bf801200a49087000bf00bf9ae7"),
     hx("002038b5344d2c78a62c1fd202f061f80346d80718d518090a2815d1e81de130006878b9980707d401342c70a62c0dd301f01afb30b90fe0012027490870a820287004e0a92000e00020287038bd01f00bfb0446012c1fd007f017ff02e00a2013f04cfc1e4800680528f8d300201b49086001201b490870002001f0e6fe012001f001fb1849c979012901d0012100e00021084602f04ff802f039fcfef713fe0a2013f02bfc02f044fc0f481049097830f811000f49c8804ff47a7013f01efc0c49c8880ef09bf801200a4908700cf078fdbbe7")),
    ("full-transition saved-gain, second-B6 and manual-lock helper", 0x0FCFC,
     hx("2de9f84304460d464ff001080027002000900220faf7dafc0646012269464ff4ea60f6f78ff89df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f25170f6f77af837883a46214640f25370f6f773f82f804ff000083046faf75dfc4046bde8f8832de9f84304460d464ff001080027002000900220faf7a2fc06460122694640f27c70f6f757f89df80000aa2806d023202070012028804ff0000813e09df80000aa280fd10222314640f27d70f6f742f837883a46214640f27f70f6f73bf82f804ff000083046faf725fc4046bde8f883"),
     hx("c6e700bf10b50c4c2078a62813d1a720207040f2d07006f092fe0849c87901214840f5f7a9fa4ff47a7006f088fe0448c08800f007f810bd480200207a0300204c0e002010b501f0c1fa082002490a7802430a7010bd00bf920d00204c0e0020920d00204c0d00206c0d002000bf00bf8ee700bf0d490878a62813d1a72008701ce00b49086001200a4908700a490a78082002430a70d63901200870fff7c7fff3f71dbafbf712f9f3f7f9b94802002088040020b60c0020920d0020022048700020dee700bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf")),
    ("mode-1 BE-before-BA wrapper hook", 0x0537E,
     hx("0020fff762fe"), hx("0af01ffd00bf")),
    ("accept native/scaler class changes", 0x04CFC,
     hx("02"), hx("03")),
    ("adaptive 72 Hz uses the native profile policy", 0x04E38,
     hx("01"), hx("00")),
    ("adaptive 72 Hz keeps mode-1 E0C0", 0x04E42,
     hx("01"), hx("00")),
    ("adaptive 90 Hz uses the native profile policy", 0x04E68,
     hx("01"), hx("00")),
    ("adaptive 90 Hz keeps mode-1 E0C0", 0x04E72,
     hx("01"), hx("00")),
    ("adaptive 120 Hz uses the native profile policy", 0x04EC8,
     hx("01"), hx("00")),
    ("adaptive 120 Hz keeps mode-1 E0C0", 0x04ED2,
     hx("01"), hx("00")),
    ("true-720p class selects logical mode 1", 0x04DEE,
     hx("012805d1"), hx("0228ead0")),
    ("mode 3 selects E0C0 RGB", 0x053D8,
     hx("0020"), hx("0220")),
    ("mode 5 selects E0C0 RGB", 0x05436,
     hx("0120"), hx("0220")),
    ("mode 4 selects E0C0 RGB", 0x0549A,
     hx("0120"), hx("0220")),
    ("mode 8 selects E0C0 RGB", 0x05504,
     hx("0020"), hx("0220")),
    ("mode 10 selects E0C0 RGB", 0x05574,
     hx("0120"), hx("0220")),
    ("mode 9 selects E0C0 RGB", 0x055DE,
     hx("0120"), hx("0220")),
    ("adaptive RGB/scaler OLED group policy", 0x04D72,
     hx("0846c07a022803d100200ff05efac9e0"),
     hx("c87a022804d1c87840080ff05efac9e0")),
    ("mode 1 compares OLED RGB group 0", 0x053B4,
     hx("0128"), hx("0028")),
    ("mode 1 selects OLED RGB group 0", 0x053B8,
     hx("0120"), hx("0020")),
    ("mode 3 compares OLED RGB group 0", 0x05414,
     hx("0128"), hx("0028")),
    ("mode 3 selects OLED RGB group 0", 0x05418,
     hx("0120"), hx("0020")),
    ("mode 5 compares OLED RGB group 0", 0x05476,
     hx("0228"), hx("0028")),
    ("mode 5 selects OLED RGB group 0", 0x0547A,
     hx("0220"), hx("0020")),
    ("mode 4 compares OLED RGB group 0", 0x054D6,
     hx("0228"), hx("0028")),
    ("mode 4 selects OLED RGB group 0", 0x054DA,
     hx("0220"), hx("0020")),
    ("mode 8 compares OLED RGB group 0", 0x05540,
     hx("0128"), hx("0028")),
    ("mode 8 selects OLED RGB group 0", 0x05544,
     hx("0120"), hx("0020")),
    ("mode 10 compares OLED RGB group 0", 0x055B0,
     hx("0228"), hx("0028")),
    ("mode 10 selects OLED RGB group 0", 0x055B4,
     hx("0220"), hx("0020")),
    ("mode 9 compares OLED RGB group 0", 0x0561A,
     hx("0228"), hx("0028")),
    ("mode 9 selects OLED RGB group 0", 0x0561E,
     hx("0220"), hx("0020")),
    ("OLED group-3 uses the four-lane link table", 0x1A65E,
     hx("d905"), hx("5803")),
    ("resolution-aware OLED group selector hook", 0x1423E,
     hx("0446042c"), hx("09f0e1fc")),
    ("initial-DP full-state apply before first OLED open", 0x0512E,
     hx("012000f0a0f8"), hx("0af04ffe00bf")),
    ("mode-1 full-state apply before first OLED reopen", 0x0539C,
     hx("c249c9790129"), hx("0af018fd0de0")),
)

GROUP_HELPER_OFFSET = 0x1DC04
GROUP_HELPER = hx(
    "04460e480e498d4202d10124c47013e0c17802290dd000290ed14179032904d0"
    "012c08d0022c06d006e0002c04d1032402e0012400e00024042c7047"
    "7a03002088040020"
)

HOTPLUG_HOOK_OFFSET = 0x04C24
HOTPLUG_HOOK = hx("19f046b8")
HOTPLUG_ACTION_OFFSET = 0x1DCB4
HOTPLUG_ACTION = hx(
    "f0b585b000f002f8e6f7b4bf"
    "f0b581b0144fe7f716fb022820d18820e7f7b8fa0446052c1ad0012c1ad1"
    "8920e7f7b0fa05469020e7f7acfa0646022d10d1042e0ed1387800280bd1"
    "01203870b620e7f79ffa01214840e7f7b3fa01e00020387001b0f0bd"
    "3a12002000bf"
)

# Applied after RECORDS because the audio-policy record creates the guarded NOP
# cave used by the mode-1 wrapper. The adjacent helper enters the official full-
# state core with an explicit state reload.
POST_RECORDS: tuple[Record, ...] = (
    ("mode-1 BE-before-BA wrapper", 0x0FDC0,
     hx("00bf" * 14),
     hx("10b50020f5f730fe0020f5f73df910bd"
        "70b5014df4f763f888040020")),
    ("resolution-aware OLED group selector", GROUP_HELPER_OFFSET,
     bytes(len(GROUP_HELPER)), GROUP_HELPER),
    ("periodic gate to powered-HDMI disconnect-edge recovery", HOTPLUG_HOOK_OFFSET,
     hx("f0b585b0"), HOTPLUG_HOOK),
    ("powered-HDMI disconnect-edge live-B6 toggle", HOTPLUG_ACTION_OFFSET,
     bytes(len(HOTPLUG_ACTION)), HOTPLUG_ACTION),
)

ALL_RECORDS = RECORDS + POST_RECORDS
RECORD_BYTES = sum(len(old) for _label, _offset, old, _new in ALL_RECORDS)


def build(stock: bytes) -> bytes:
    out = bytearray(stock)
    for label, offset, old, new in RECORDS:
        if len(old) != len(new):
            fail(f"record length mismatch: {label}")
        if out[offset:offset + len(old)] != old:
            fail(f"stock guard mismatch at 0x{offset:05X}: {label}")
        out[offset:offset + len(new)] = new
    for label, offset, old, new in POST_RECORDS:
        if out[offset:offset + len(old)] != old:
            fail(f"derived guard mismatch at 0x{offset:05X}: {label}")
        out[offset:offset + len(new)] = new
    fix_container_crc(out)
    return bytes(out)


def verify_stock(stock: bytes) -> None:
    validate_container(stock, "stock image")
    digest = sha256(stock)
    if digest != STOCK_SHA256:
        fail("this is not the expected official Air 2 MCU image.\n"
             f"       expected SHA-256 {STOCK_SHA256}\n"
             f"       got             {digest}")
    if head(stock)["stored_crc"] != STOCK_CRC:
        fail(f"stock container CRC is 0x{head(stock)['stored_crc']:08X}, expected 0x{STOCK_CRC:08X}")
    for label, offset, old, _new in RECORDS:
        if stock[offset:offset + len(old)] != old:
            fail(f"stock guard mismatch at 0x{offset:05X}: {label}")


def hotplug_edge_step(
    latch: int, e086: int, e088: int, e089: int, e090: int, b6: int
) -> tuple[int, int | None]:
    """Model the production helper's one-toggle-per-disconnect policy."""
    if e086 != 2 or e088 == 5:
        return 0, None
    if (e088, e089, e090) != (1, 2, 4) or latch:
        return latch, None
    return 1, b6 ^ 1


def verify_hotplug_model() -> None:
    if hotplug_edge_step(0, 2, 1, 2, 4, 1) != (1, 0):
        fail("powered-hotplug first disconnect did not toggle B6 1->0")
    if hotplug_edge_step(1, 2, 1, 2, 4, 0) != (1, None):
        fail("powered-hotplug disconnect latch retriggered")
    if hotplug_edge_step(1, 2, 1, 3, 11, 0) != (1, None):
        fail("powered-hotplug transition cleared the disconnect latch")
    if hotplug_edge_step(1, 2, 5, 0, 11, 0) != (0, None):
        fail("powered-hotplug reconnect did not arm the next edge")
    if hotplug_edge_step(0, 2, 1, 2, 4, 0) != (1, 1):
        fail("powered-hotplug second disconnect did not toggle B6 0->1")


def verify_output(stock: bytes, image: bytes) -> None:
    validate_container(image, "built image")
    verify_hotplug_model()
    if image != build(stock) or build(stock) != build(stock):
        fail("build is not deterministic")

    allowed = set(range(4))
    for _label, offset, old, _new in ALL_RECORDS:
        allowed.update(range(offset, offset + len(old)))
    diffs = [i for i, (before, after) in enumerate(zip(stock, image)) if before != after]
    stray = [i for i in diffs if i not in allowed]
    if stray:
        fail("changed bytes outside the record set: " + " ".join(f"0x{i:05X}" for i in stray))
    if len(diffs) != EXPECTED_DIFFS:
        fail(f"changed-byte count is {len(diffs)}, expected {EXPECTED_DIFFS}")

    h = head(image)
    if sha256(image) != OUTPUT_SHA256:
        fail(f"output SHA-256 mismatch: {sha256(image)}")
    if h["stored_crc"] != OUTPUT_CRC:
        fail(f"container CRC mismatch: 0x{h['stored_crc']:08X}")

    # Pin the safety-critical order: clear mode-9-only BE before setBA(0).
    wrapper = image[0x0FDC0:0x0FDD0]
    if wrapper != hx("10b50020f5f730fe0020f5f73df910bd"):
        fail("mode-1 BE-before-BA wrapper mismatch")
    if image[0x0504A:0x0504C] != hx("0446"):
        fail("official E0C0 setter was modified")
    if image[0x0512E:0x05134] != hx("0af04ffe00bf"):
        fail("initial-DP full-state hook mismatch")
    if image[0x1423E:0x14242] != hx("09f0e1fc"):
        fail("OLED group selector hook mismatch")
    if image[0x0502A:0x05046] != hx(
        "10b5e021ff2000f0d6fcc02000f005f90446032c00db0024204610bd"
    ):
        fail("official live C0 getter changed")
    if image[0x04D5A:0x04D6A] != hx("00f0a7f97249887200f062f97049c872"):
        fail("C0 getter no longer follows the E0-bank-selecting BF getter")
    if image[0x0539C:0x053A2] != hx("0af018fd0de0"):
        fail("mode-1 full-state hook mismatch")
    if image[FULL_TRANSITION_HOOK_OFFSET:FULL_TRANSITION_HOOK_OFFSET + len(FULL_TRANSITION_HOOK)] != FULL_TRANSITION_HOOK:
        fail("no-USB path no longer enters the official full DP-audio transition")
    if image[FULL_TRANSITION_HELPER_OFFSET:FULL_TRANSITION_HELPER_OFFSET + len(FULL_TRANSITION_HELPER)] != FULL_TRANSITION_HELPER:
        fail("full-transition saved-gain/manual-lock helper mismatch")
    if image[0x0FDD0:0x0FDDC] != hx("70b5014df4f763f888040020"):
        fail("mode-1 full-state helper mismatch")
    if image[0x05648:0x0568C] != stock[0x05648:0x0568C]:
        fail("mode-11 C0=1 / OLED group-3 path changed")
    if image[GROUP_HELPER_OFFSET:GROUP_HELPER_OFFSET + len(GROUP_HELPER)] != GROUP_HELPER:
        fail("resolution-aware OLED group selector mismatch")
    if image[HOTPLUG_HOOK_OFFSET:HOTPLUG_HOOK_OFFSET + len(HOTPLUG_HOOK)] != HOTPLUG_HOOK:
        fail("powered-hotplug periodic hook mismatch")
    if image[HOTPLUG_ACTION_OFFSET:HOTPLUG_ACTION_OFFSET + len(HOTPLUG_ACTION)] != HOTPLUG_ACTION:
        fail("powered-hotplug disconnect-edge helper mismatch")
    if image[0x03DA8:0x03DAC] != hx("02460120"):
        fail("stock host-message 0x9B handler changed")
    if image[0x1DC48:0x1DCB4] != bytes(108):
        fail("removed powered-hotplug diagnostic cave is not empty")
    for offset in (0x04DA2, 0x04E42, 0x04E72, 0x04ED2, 0x05122, 0x0FDC8):
        if image[offset] != 0:
            fail("mode-1 E0C0 policy mismatch")
    if image[0x04DEE:0x04DF2] != hx("0228ead0"):
        fail("true-720p logical-mode selection mismatch")
    for offset, expected in ((0x1A4E0, hx("5803")), (0x0104A, hx("d904")),
                             (0x1A65E, hx("5803"))):
        if image[offset:offset + 2] != expected:
            fail(f"OLED link-table contract mismatch at 0x{offset:05X}")

    print("=== XREAL Air 2 / Air 2 Pro - target-converter MCU ===")
    print("  stock input     : SHA-256 and container CRC verified")
    print(f"  records applied : {len(ALL_RECORDS)} ({RECORD_BYTES} guarded bytes)")
    print(f"  changed bytes   : {len(diffs)} (records + header CRC)")
    print("  no-USB state    : initial-wait official full DP-audio transition")
    print("  audio EDID      : E0B8/B6/HPD re-enumeration; blackout expected")
    print("  audio route     : DP-I2S + SmartPA, saved gain restored")
    print("  retry           : second B6 after a 2-second fixed delay")
    print("  manual switch   : audio-mode long press locked for the no-USB session")
    print("  mode transition : mode 1 clears BE before changing BA")
    print("  initial display : full-state apply before the first OLED open/reopen")
    print("  native RGB      : group 0; 120 Hz uses group 3 timing")
    print("  true 720p       : official group 1 / YCbCr scaler table")
    print("  HDMI hotplug    : exact disconnect edge toggles live B6 once")
    print("  reconnect       : no MCU action; converter delayed retrain retained")
    print("  protected code  : bytes outside guarded records remain official")
    print(f"  container CRC   : 0x{h['stored_crc']:08X}")
    print(f"  sha256          : {sha256(image)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Air 2-family target-converter MCU image from official firmware.",
        epilog="You supply the official firmware. This tool contains no firmware and touches no hardware.",
    )
    parser.add_argument("--src", type=Path, required=True, metavar="STOCK_MCU")
    parser.add_argument("--out", type=Path, metavar="FILE")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--verify", type=Path, metavar="FILE")
    args = parser.parse_args()
    if not (args.out or args.check_only or args.verify):
        parser.error("choose one of --out, --check-only, --verify")

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
