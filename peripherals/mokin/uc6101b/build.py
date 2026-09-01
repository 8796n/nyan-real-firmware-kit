#!/usr/bin/env python3
"""Build the verified MOKIN UC6101B Nintendo Switch 2 compatibility image.

The tool accepts one exact official Intel HEX image, applies a guarded patch,
recalculates the LT8712SX Block 1 CRC, and verifies the deterministic result.
It never downloads firmware or accesses hardware.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path


STOCK_SHA256 = "BE3C7FD831B7D3C1C6D822D70C72EACF2DA21958E03C6448A9857DB6D762AA7D"
OUTPUT_SHA256 = "0DB0BF009776115FA890BDE71C6CC858CD102693A4B3D2CEF99F207826372CF1"
OUTPUT_CHECKSUM = 0x11520DA

FALLBACK_OFFSET = 0xD51F
RESET_TAIL_OFFSET = 0xF27C
RESET_STUB_OFFSET = 0xF89D
BLOCK1_CRC_OFFSET = 0xFFFF

FALLBACK_BEFORE = bytes.fromhex("39")
FALLBACK_AFTER = bytes.fromhex("86")
RESET_TAIL_BEFORE = bytes.fromhex("02 61 19")
RESET_TAIL_AFTER = bytes.fromhex("02 F8 9D")
RESET_STUB = bytes.fromhex(
    "12 61 19"       # LCALL 0x6119: finish the original reset operation
    " E4 FF"         # CLR A; MOV R7,A
    " 12 F8 45"      # LCALL 0xF845: clear XDATA 0xA110 bit 1
    " 7F 64 7E 00"   # delay argument 0x0064
    " 12 B5 8E"      # LCALL 0xB58E: delay
    " 7F 01"         # MOV R7,#1
    " 02 F8 45"      # LJMP 0xF845: set XDATA 0xA110 bit 1 and return
)
BLOCK1_CRC_BEFORE = bytes.fromhex("82")


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


@dataclass
class Record:
    kind: int
    offset: int
    data: bytearray
    absolute: int | None

    def encode(self) -> str:
        body = bytes((len(self.data), self.offset >> 8, self.offset & 0xFF, self.kind)) + self.data
        return ":" + (body + bytes(((-sum(body)) & 0xFF,))).hex().upper()


def read_records(raw: bytes, source: Path) -> list[Record]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"{source}: Intel HEX must be ASCII") from error

    records: list[Record] = []
    base = 0
    eof_seen = False
    for line_no, line in enumerate(lines, 1):
        if not line:
            continue
        if eof_seen:
            raise ValueError(f"{source}:{line_no}: record after EOF")
        if not line.startswith(":"):
            raise ValueError(f"{source}:{line_no}: not an Intel HEX record")
        try:
            packed = bytes.fromhex(line[1:])
        except ValueError as error:
            raise ValueError(f"{source}:{line_no}: invalid hexadecimal data") from error
        if len(packed) < 5 or len(packed) != packed[0] + 5 or sum(packed) & 0xFF:
            raise ValueError(f"{source}:{line_no}: invalid Intel HEX record")

        size = packed[0]
        offset = int.from_bytes(packed[1:3], "big")
        kind = packed[3]
        data = bytearray(packed[4 : 4 + size])
        if kind not in (0, 1, 2, 3, 4, 5):
            raise ValueError(f"{source}:{line_no}: unsupported record type {kind}")
        if kind in (2, 4) and size != 2:
            raise ValueError(f"{source}:{line_no}: invalid base-address record")

        absolute = base + offset if kind == 0 else None
        records.append(Record(kind, offset, data, absolute))
        if kind == 1:
            eof_seen = True
        elif kind == 2:
            base = int.from_bytes(data, "big") << 4
        elif kind == 4:
            base = int.from_bytes(data, "big") << 16

    if not eof_seen:
        raise ValueError(f"{source}: EOF record not found")
    image(records)
    return records


def image(records: list[Record]) -> dict[int, int]:
    result: dict[int, int] = {}
    for record in records:
        if record.absolute is None:
            continue
        for index, value in enumerate(record.data):
            address = record.absolute + index
            if address in result and result[address] != value:
                raise ValueError(f"conflicting data at 0x{address:06X}")
            result[address] = value
    return result


def replace(records: list[Record], offset: int, before: bytes, after: bytes) -> None:
    if len(before) != len(after):
        raise AssertionError("guarded replacement must preserve length")
    pending = {offset + index: (old, new) for index, (old, new) in enumerate(zip(before, after))}
    for record in records:
        if record.absolute is None:
            continue
        for index, value in enumerate(record.data):
            address = record.absolute + index
            if address not in pending:
                continue
            old, new = pending.pop(address)
            if value != old:
                raise ValueError(
                    f"guard failed at 0x{address:06X}: expected 0x{old:02X}, got 0x{value:02X}"
                )
            record.data[index] = new
    if pending:
        missing = ", ".join(f"0x{address:06X}" for address in sorted(pending))
        raise ValueError(f"guarded addresses not present: {missing}")


def insert_data(records: list[Record], offset: int, data: bytes) -> None:
    occupied = image(records)
    overlap = [address for address in range(offset, offset + len(data)) if address in occupied]
    if overlap:
        raise ValueError(f"patch space is not empty at 0x{overlap[0]:06X}")
    eof = next(index for index, record in enumerate(records) if record.kind == 1)
    records[eof:eof] = [
        Record(4, 0, bytearray(b"\x00\x00"), None),
        Record(0, offset, bytearray(data), offset),
    ]


def crc8_dallas(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def filled_checksum(memory: dict[int, int]) -> int:
    return sum(memory.get(address, 0xFF) for address in range(max(memory) + 1))


def encode(records: list[Record]) -> bytes:
    return ("\r\n".join(record.encode() for record in records) + "\r\n").encode("ascii")


def build(stock_raw: bytes, source: Path) -> bytes:
    digest = sha256(stock_raw)
    if digest != STOCK_SHA256:
        fail(
            "this is not the supported official UC6101B image\n"
            f"       expected SHA-256 {STOCK_SHA256}\n"
            f"       got             {digest}"
        )

    records = read_records(stock_raw, source)
    stock = image(records)
    replace(records, FALLBACK_OFFSET, FALLBACK_BEFORE, FALLBACK_AFTER)
    replace(records, RESET_TAIL_OFFSET, RESET_TAIL_BEFORE, RESET_TAIL_AFTER)
    insert_data(records, RESET_STUB_OFFSET, RESET_STUB)

    memory = image(records)
    crc = crc8_dallas(bytes(memory.get(address, 0xFF) for address in range(BLOCK1_CRC_OFFSET)))
    replace(records, BLOCK1_CRC_OFFSET, BLOCK1_CRC_BEFORE, bytes((crc,)))
    memory = image(records)

    expected_changes = {FALLBACK_OFFSET, RESET_TAIL_OFFSET + 1, RESET_TAIL_OFFSET + 2, BLOCK1_CRC_OFFSET}
    expected_changes.update(range(RESET_STUB_OFFSET, RESET_STUB_OFFSET + len(RESET_STUB)))
    changed = {
        address
        for address in stock.keys() | memory.keys()
        if stock.get(address) != memory.get(address)
    }
    if changed != expected_changes:
        unexpected = changed ^ expected_changes
        fail("changed-address contract mismatch: " + " ".join(f"0x{x:06X}" for x in sorted(unexpected)))
    if memory[BLOCK1_CRC_OFFSET] != crc8_dallas(
        bytes(memory.get(address, 0xFF) for address in range(BLOCK1_CRC_OFFSET))
    ):
        fail("Block 1 CRC-8 verification failed")
    if filled_checksum(memory) != OUTPUT_CHECKSUM:
        fail(f"image checksum mismatch: 0x{filled_checksum(memory):X}")

    output = encode(records)
    if sha256(output) != OUTPUT_SHA256:
        fail(f"output SHA-256 mismatch: {sha256(output)}")

    print("=== MOKIN UC6101B - Nintendo Switch 2 compatibility ===")
    print(f"  stock input     : SHA-256 {digest}")
    print("  response        : unknown Nintendo VDM -> type 0x20 fallback")
    print("  reset           : XDATA 0xA110 bit 1 clear, delay, set")
    print(f"  changed bytes   : {len(changed)}")
    print(f"  Block 1 CRC-8   : 0x{memory[BLOCK1_CRC_OFFSET]:02X}")
    print(f"  image checksum  : 0x{filled_checksum(memory):X}")
    print(f"  sha256          : {sha256(output)}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the verified UC6101B Nintendo Switch 2 compatibility image.",
        epilog="You supply the official firmware. This tool contains no firmware and touches no hardware.",
    )
    parser.add_argument("--src", type=Path, required=True, metavar="STOCK_HEX")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--out", type=Path, metavar="FILE")
    action.add_argument("--check-only", action="store_true")
    action.add_argument("--verify", type=Path, metavar="FILE")
    args = parser.parse_args()

    try:
        stock_raw = args.src.read_bytes()
        output = build(stock_raw, args.src)
    except (OSError, ValueError) as error:
        fail(str(error))

    if args.verify:
        try:
            candidate = args.verify.read_bytes()
        except OSError as error:
            fail(str(error))
        if candidate != output:
            fail(f"{args.verify} differs from the deterministic build")
        print(f"  verify          : {args.verify} [byte-identical]")
    elif args.check_only:
        print("  check-only      : nothing written")
    else:
        if args.out.resolve() == args.src.resolve():
            fail("refusing to overwrite the stock image")
        try:
            args.out.write_bytes(output)
        except OSError as error:
            fail(str(error))
        print(f"  wrote           : {args.out}")
    print("  hardware access : none")


if __name__ == "__main__":
    main()
