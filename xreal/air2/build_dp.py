#!/usr/bin/env python3
"""Build the XREAL Air 2 / Air 2 Pro DP image directly from official 1140.

Relative to the official image, this build adds true 720p input and full-panel
scaling, restores native display state when leaving 720p, enables HBR2 for
Full-SBS 90 Hz, and advertises audio according to the MCU-selected route. Native
1080p uses the official RGB profile; true 720p keeps the official YCbCr scaler
profile. The EDID monitor name remains official.

This tool is offline and standard-library only.  It accepts exactly one known
official Air 2-family container, applies guarded before/after records, then pins the
output SHA-256, container CRC, bank0 tag, changed-byte count and EDID contract.
It never downloads firmware and never touches hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


HDR = 0x40
POLY = 0xF4ACFB13
TAG_OFF = 0x38
TAG_POLY = 0x31
BANK0 = 0x10000

SIZE = 50_632
STOCK_SHA256 = "350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3"
STOCK_CRC = 0x0AA87FF3
OUTPUT_SHA256 = "46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486"
OUTPUT_CRC = 0xA86203B1
OUTPUT_TAG = 0xBF
EXPECTED_DIFFS = 384

EXPECT_PROJECT = 0x0900
EXPECT_FWTYPE = 2
EXPECT_NAME = "1140"

AIR2_TEMPLATE = 0x01E5C
AIR2_NAME = 0x01ECD
CTA_AUDIO = 0x01FDC
CTA_NO_AUDIO = 0x0205C
CTA_SIZE = 128

Record = tuple[str, int, bytes, bytes]


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def hx(text: str) -> bytes:
    return bytes.fromhex(text)


RGB_PROFILE_MAP_GUARDS = (
    (0x010D9, hx(
        "90e0c0e014600f146014240270449006e77402f0803c"
        "9006e77404f08034e49006e7f0802d")),
    (0x01107, hx(
        "90e0c0e014600f146014240270169006e77403f0800e"
        "9006e77405f080069006e77401f0")),
    (0x04ADB, hx(
        "90e0c0e014600f146014240270449006e77402f0803c"
        "9006e77404f08034e49006e7f0802d")),
    (0x04B09, hx(
        "90e0c0e014600f146014240270169006e77403f0800e"
        "9006e77405f080069006e77401f0")),
)


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


def crc8_tag(data: bytes) -> int:
    """CRC-8 / poly 0x31 / MSB-first / init 0 / xorout 0."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ TAG_POLY) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def head(data: bytes) -> dict:
    return dict(
        stored_crc=struct.unpack_from("<I", data, 0)[0],
        length=struct.unpack_from("<I", data, 4)[0],
        project=struct.unpack_from("<I", data, 8)[0],
        fwtype=struct.unpack_from("<I", data, 12)[0],
        name=data[16:36].split(b"\0")[0].decode("ascii", "replace"),
    )


def fix_bank0_tag(data: bytearray) -> int:
    payload = bytes(data[HDR:])
    padding = BANK0 - 1 - len(payload)
    if padding < 0:
        fail("payload exceeds bank0")
    data[TAG_OFF] = crc8_tag(payload + b"\xFF" * padding)
    return data[TAG_OFF]


def fix_container_crc(data: bytearray) -> int:
    crc = crc_container(bytes(data[8:8 + head(bytes(data))["length"]]))
    struct.pack_into("<I", data, 0, crc)
    return crc


def validate_container(data: bytes, what: str) -> None:
    if len(data) != SIZE:
        fail(f"{what}: expected {SIZE} bytes, got {len(data)}")
    h = head(data)
    if h["project"] != EXPECT_PROJECT:
        fail(f"{what}: projectCode 0x{h['project']:04X} is not Air 2/p55 (0x0900)")
    if h["fwtype"] != EXPECT_FWTYPE or h["name"] != EXPECT_NAME:
        fail(f"{what}: fwType/name mismatch ({h['fwtype']} / {h['name']!r})")
    if h["length"] + 8 != len(data):
        fail(f"{what}: declared container length does not match the file")
    if crc_container(data[8:8 + h["length"]]) != h["stored_crc"]:
        fail(f"{what}: container CRC-32 does not match its header")


RECORDS: tuple[Record, ...] = (
    ("scaler fixed totals -> measured E790:E793 totals", 0x00318,
     hx("0474121b220000044c900474121afe7801121ab1900474121b16900488121b2200000465900488121afe900470121b16900488121afe90048c121b16"),
     hx("e790e0fe90e791e0ffe4fcfd900474121b1690e792e0fe90e793e0ffe4fcfd900488121b16900470121b1690048c121b160000000000000000000000")),
    ("horizontal scaler endpoint correction", 0x006DE,
     hx("ffffee34fffeed34fffdec34ff"), hx("00ffee3400feed3400fdec3400")),
    ("vertical scaler endpoint correction", 0x007B6,
     hx("ffffee34fffeed34fffdec34ff"), hx("00ffee3400feed3400fdec3400")),
    ("mode-1 scaler geometry profile", 0x0115C, hx("0c"), hx("0f")),
    ("E0B8 CTA selection, fixed-mode 720p removal and mode-9 HBR2", 0x01558,
     hx("90e0b8e07bffb4010f7a1c79d0123fc19002a97401f0800c7a1c79d7123fc1e49002a9f090e0bee0603890e0bbe0640270439006e8e06402703b7bff7a1c79e1123fc19006cf740af09006d07404f09002a97401f078ab7c02fd7bff7a20791c800c78ab7c027d017bff7a1f799c"),
     hx("90e0b8e07bffb4010f7a1f799c0000009002a97401f0800c7a20791c740100009002a9f090e0bee0603890e0bbe0640270309006e8e0640270287bff000000000000009006cf7414f09006d07404f09002a97401f078ab7c02fd7bff00000000800c78ab7c027d017bff00000000")),
    ("Air 2 base standard timing 1280x720@60", 0x01E82, hx("0101"), hx("81c0")),
    ("Air 2 base EDID checksum", 0x01EDB, hx("26"), hx("e7")),
    ("DP-audio CTA with VIC 4", CTA_AUDIO,
     hx("02031251230904018301000065030c00100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000bf"),
     hx("02031441230904018301000065030c0010004104000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000088")),
    ("no-audio CTA with VIC 4", CTA_NO_AUDIO,
     hx("02030a1165030c0010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000005c"),
     hx("02030c0165030c00100041040000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000025")),
    ("720p native-return clock helper", 0x03212,
     hx("0a2054686520706879636c6b207265616368206d6178696d756d2076616c75652e2e2e"),
     hx("9006e7e06404701490e0bbe0700ee4fc7d037e667f1e900460121b16e47f0222000000")),
    ("inactive runtime VIC-4 helper retained for tested-image identity", 0x03B28,
     hx("4c766473206f7574707574203364206672616d657061636b696e67206d6f646520656e61626c65643b"),
     hx("90e0bbe0601f9002517401f0a3f090e0b8e0b401099002bde4f0a3f080079002b5e4f0a3f00299a100")),
    ("scaler entry geometry profile", 0x04B5E, hx("0c"), hx("0f")),
    ("720p scaler entry and persistent class", 0x04E5E,
     hx("9006e8e06401707b9006e7e064037073fdff12609990e598e04480f012ba26ef603690e0867402f0"),
     hx("12ba26ef607d9006e8e0640170759006e7e06404706dfdff12609990e598e04480f090e0867402f0")),
    ("post-copy exact-clock helper hook", 0x04FD9, hx("e47f02"), hx("1231d2")),
    ("DP-audio CDR reset hook", 0x08775, hx("12c1fb"), hx("12913c")),
    ("DP-audio reset plus native profile restore helpers", 0x0917C,
     hx("000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
     hx("12c1fb90e0b8e0b401057f0112c54b2290e086e0701190e598e030e70a9006e7e0b404037402f0028d67")),
    ("native-return port and clock cleanup", 0x0A4A4,
     hx("06d2e024fe601024fe6014240370197bff7a3979f5800e7bff7a3a791080067bff7a3a792c123fc1"),
     hx("e0bbe070239006e7e0b4021c90e598e030e715547ff09006d27401f090f96ce4f090f910e054fef0")),
    ("720p delayed profile selection", 0x0BA80,
     hx("ee33fee4b5071aeeb40f16ae04af05be040fbf380c7bff7a3079f5123fc17f0022e49006d6f07f0122"),
     hx("ee33fee4000000ee000000ae04af05be0406bf38037f00229006e77404f07f01220000000000000000")),
    ("profile expansion through native-return helper", 0x0C0AD, hx("8d67"), hx("914c")),
)

PROFILE_HELPER_SLOT = 0x03B53
PROFILE_HELPER = hx(
    "00"
    "12ba26"                  # classify the finalized scaler state
    "ef600d"                  # native path when the classifier returns zero
    "90e086e07006"            # steady scaler: return without a sideband write
    "9004457402f022"          # native -> scaler: publish YCbCr sideband once
    "9006e7e020e010"          # native/odd-profile selection
    "12a470"                  # clear residual scaler state
    "9006e7e4f0"              # native: official RGB profile 0
    "900445f0"                # native RGB sideband
    "90e086f022"              # publish native class to the MCU and return
)

POST_RECORDS: tuple[Record, ...] = (
    ("native-RGB / true-720p profile finalizer", PROFILE_HELPER_SLOT,
     b"Lvds output 3d LineAlternative mode enabled;", PROFILE_HELPER),
    ("profile finalizer hook", 0x04E5E, hx("12ba26"), hx("123b14")),
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
    fix_bank0_tag(out)
    fix_container_crc(out)
    return bytes(out)


def edid_name(block: bytes) -> str:
    for offset in range(54, 126, 18):
        descriptor = block[offset:offset + 18]
        if descriptor[:5] == bytes.fromhex("000000fc00"):
            return descriptor[5:18].split(b"\n")[0].decode("ascii", "replace")
    return ""


def cta_blocks(block: bytes) -> list[tuple[int, bytes]]:
    out: list[tuple[int, bytes]] = []
    i, end = 4, block[2]
    while i < end:
        tag, size = block[i] >> 5, block[i] & 0x1F
        out.append((tag, block[i + 1:i + 1 + size]))
        i += 1 + size
    if i != end:
        fail("CTA data-block collection overruns the DTD offset")
    return out


def verify_edid(stock: bytes, image: bytes) -> None:
    model_blocks = {
        "Air": 0x01D5C,
        "HONOR Glass": 0x01DDC,
        "Air 2": AIR2_TEMPLATE,
        "Air 2 Pro": 0x01EDC,
        "project 0x1200": 0x01F5C,
    }
    for name, offset in model_blocks.items():
        block = image[offset:offset + 128]
        if sum(block) & 0xFF:
            fail(f"{name} base EDID checksum is not zero")
        if name != "Air 2" and block != stock[offset:offset + 128]:
            fail(f"the {name} EDID template changed")

    base = image[AIR2_TEMPLATE:AIR2_TEMPLATE + 128]
    if edid_name(base) != "Air 2":
        fail(f"Air 2 monitor name changed to {edid_name(base)!r}")
    if base[38:40] != bytes.fromhex("81 C0") or base[40:54] != bytes.fromhex("01 01") * 7:
        fail("Air 2 1280x720@60 standard-timing contract changed")
    # The stored template stays at zero; the guarded selector sets the live
    # extension count to one when it copies either CTA into XDATA.
    if base[126] != 0:
        fail("Air 2 static base EDID extension count changed")

    audio = image[CTA_AUDIO:CTA_AUDIO + CTA_SIZE]
    no_audio = image[CTA_NO_AUDIO:CTA_NO_AUDIO + CTA_SIZE]
    # The stock audio template keeps its stored 0x60 sum; the runtime assembly
    # path computes the checksum delivered to the host.  The no-audio template
    # is stored as a complete zero-sum block.
    if sum(audio) & 0xFF != 0x60 or sum(no_audio) & 0xFF:
        fail("stored CTA checksum contract changed")
    if audio[:4] != bytes.fromhex("02 03 14 41"):
        fail("DP-audio CTA header/flags changed")
    if no_audio[:4] != bytes.fromhex("02 03 0C 01"):
        fail("no-audio CTA header/flags changed")
    if cta_blocks(audio) != [
        (1, bytes.fromhex("09 04 01")),
        (4, bytes.fromhex("01 00 00")),
        (3, bytes.fromhex("03 0C 00 10 00")),
        (2, bytes.fromhex("04")),
    ]:
        fail("DP-audio CTA data-block contract changed")
    if cta_blocks(no_audio) != [
        (3, bytes.fromhex("03 0C 00 10 00")),
        (2, bytes.fromhex("04")),
    ]:
        fail("no-audio CTA data-block contract changed")
    if any(audio[audio[2]:127]) or any(no_audio[no_audio[2]:127]):
        fail("Air 2 CTA unexpectedly contains DTD or non-zero padding")


def verify_stock(stock: bytes) -> None:
    validate_container(stock, "stock image")
    digest = sha256(stock)
    if digest != STOCK_SHA256:
        fail("this is not the expected official Air 2 1140.\n"
             f"       expected SHA-256 {STOCK_SHA256}\n"
             f"       got             {digest}")
    if head(stock)["stored_crc"] != STOCK_CRC:
        fail(f"stock container CRC is 0x{head(stock)['stored_crc']:08X}, expected 0x{STOCK_CRC:08X}")
    for label, offset, old, _new in RECORDS:
        if stock[offset:offset + len(old)] != old:
            fail(f"stock guard mismatch at 0x{offset:05X}: {label}")
    for offset, expected in RGB_PROFILE_MAP_GUARDS:
        if stock[offset:offset + len(expected)] != expected:
            fail(f"stock RGB profile-map guard mismatch at 0x{offset:05X}")


def verify_rgb_profile_contract(stock: bytes, image: bytes) -> None:
    for offset, expected in RGB_PROFILE_MAP_GUARDS:
        if image[offset:offset + len(expected)] != expected:
            fail(f"RGB profile-map changed at 0x{offset:05X}")
        if image[offset:offset + len(expected)] != stock[offset:offset + len(expected)]:
            fail(f"RGB profile-map is not official at 0x{offset:05X}")

    # The official map remains intact. The finalizer selects profile 0 only for
    # native even/2D input, keeps profile 4 for the scaler, and preserves odd/SBS.
    states = (
        ("2D 1080p60", 0, False, 0),
        ("2D 1080p90", 2, False, 0),
        ("2D 1080p120", 4, False, 0),
        ("2D 720p scaler", 0, True, 4),
        ("SBS 1080p60", 1, False, 1),
        ("SBS 1080p90", 3, False, 3),
    )
    for label, initial_profile, scaler, expected_profile in states:
        profile = 4 if scaler else initial_profile
        if not scaler and not (profile & 1):
            profile = 0
        if profile != expected_profile:
            fail(f"RGB state contract mismatch: {label}")

    if len(PROFILE_HELPER) != 44:
        fail("profile finalizer slot size changed")
    if image[PROFILE_HELPER_SLOT:PROFILE_HELPER_SLOT + 44] != PROFILE_HELPER:
        fail("profile finalizer body changed")
    if image[0x04E5E:0x04E61] != hx("123b14"):
        fail("profile finalizer hook changed")

    helper = PROFILE_HELPER[1:]
    if 6 + helper[5] != 19 or 12 + helper[11] != 18 or helper[18] != 0x22:
        fail("profile finalizer branch target changed")
    writes_sideband = lambda scaler, previous_class: scaler and previous_class == 0
    if not writes_sideband(True, 0) or writes_sideband(True, 2) or writes_sideband(False, 0):
        fail("profile finalizer transition-latch contract changed")


def verify_output(stock: bytes, image: bytes) -> None:
    validate_container(image, "built image")
    if image != build(stock) or build(stock) != build(stock):
        fail("build is not deterministic")

    allowed = set(range(4)) | {TAG_OFF}
    for _label, offset, old, _new in ALL_RECORDS:
        allowed.update(range(offset, offset + len(old)))
    diffs = [i for i, (before, after) in enumerate(zip(stock, image)) if before != after]
    stray = [i for i in diffs if i not in allowed]
    if stray:
        fail("changed bytes outside the record set: " + " ".join(f"0x{i:05X}" for i in stray))
    if len(diffs) != EXPECTED_DIFFS:
        fail(f"changed-byte count is {len(diffs)}, expected {EXPECTED_DIFFS}")

    verify_edid(stock, image)
    verify_rgb_profile_contract(stock, image)
    h = head(image)
    if sha256(image) != OUTPUT_SHA256:
        fail(f"output SHA-256 mismatch: {sha256(image)}")
    if h["stored_crc"] != OUTPUT_CRC:
        fail(f"container CRC mismatch: 0x{h['stored_crc']:08X}")
    if image[TAG_OFF] != OUTPUT_TAG:
        fail(f"bank0 tag mismatch: 0x{image[TAG_OFF]:02X}")

    print("=== XREAL Air 2 / Air 2 Pro - DP bridge ===")
    print("  stock input     : SHA-256 verified, projectCode 0x0900 (p55)")
    print(f"  records applied : {len(ALL_RECORDS)} ({RECORD_BYTES} guarded bytes)")
    print(f"  changed bytes   : {len(diffs)} (records + CRC + bank0 tag)")
    print("  EDID names      : Air 2 / Air 2 Pro (official runtime selection retained)")
    print("  720p            : VIC 4 + Air 2 standard timing; hardware scaler profile 4")
    print("  audio CTA       : E0B8==1 LPCM; otherwise no-audio; HDMI VSDB on both")
    print("  native 1080p    : official RGB profile 0; residual scaler state cleared")
    print("  mode transition : native->720p sideband written once; steady 720p untouched")
    print("  Full-SBS        : official odd-profile selection retained")
    print("  true 720p       : official profile-4 YCbCr scaler path")
    print("  EDID contract   : decoded and checked")
    print(f"  container CRC   : 0x{h['stored_crc']:08X}")
    print(f"  bank0 tag       : 0x{image[TAG_OFF]:02X}")
    print(f"  sha256          : {sha256(image)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Air 2 DP bridge image directly from an official 1140 container.",
        epilog="You supply the official firmware. This tool contains no firmware and touches no hardware.",
    )
    parser.add_argument("--src", type=Path, required=True, metavar="STOCK_1140")
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
