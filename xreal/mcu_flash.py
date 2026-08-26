#!/usr/bin/env python3
r"""Write XREAL Air-family MCU application firmware over USB HID.

Air, Air 2 and Air 2 Pro use the same MCU update opcodes but not the same wire
sequence. The connected PID selects the sequence; the image must also have a
known byte-exact SHA-256 and match that model.

    Air                 APP/BOOT 0424/0423, START [0:24]
    Air 2               APP/BOOT 0428/0427, START [0:42] + [42:64]
    Air 2 Pro           APP/BOOT 0432/0431, same format and images as Air 2

The official updater sends a short final TRANSMIT twice on both formats. Its
current Web build soft-waits for JUMP_TO_BOOT on both models but does not use
the returned status. This writer follows tested hardware behavior instead:
Air re-enumerates without a reliable reply, while Air 2 must return status 0.

Only the MCU application area is written. If an application does not start,
the separate BOOT PID remains the recovery path. An already-BOOT device may
only receive its byte-exact stock image.

No firmware-update command is sent unless --flash is present. --verify-only
does not enumerate or open USB. The tool never downloads or redistributes
firmware.

Examples:
  python xreal/mcu_flash.py
  python xreal/mcu_flash.py --image air-mcu.bin
  python xreal/mcu_flash.py --image air2-mcu.bin --verify-only
  python xreal/mcu_flash.py --image air2-mcu.bin --flash
  python xreal/mcu_flash.py --restore --flash
  python xreal/mcu_flash.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import hid
from air import build_mcu as air_build
from air2 import build_mcu as air2_build


PREPARE, START, TRANSMIT, FINISH, JUMP_TO_APP, JUMP_TO_BOOT = 62, 63, 64, 65, 66, 68
R_MCU_APP_FW_VERSION = 38
CHUNK = 42
VID, CTRL_IF = 0x3318, 4

# The official common updater scans these legacy vendor ids too. Rejecting any
# extra XREAL/Nreal HID device makes "connect exactly one pair" enforceable.
XREAL_VIDS = (VID, 0x0486, 0x0483, 0x0482)


def cmd_build(msgid: int, payload: bytes = b"") -> bytes:
    # Lazy import keeps --verify-only free of the device scan in glasses.py.
    from dp_flash import cmd_build as build

    return build(msgid, payload)


def parse_rsp(data: bytes) -> dict | None:
    from dp_flash import parse_rsp as parse

    return parse(data)


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    app_pid: int
    boot_pid: int
    stock: Path
    stock_sha256: str
    version: str
    starts: tuple[tuple[int, int], ...]
    jump_ack: bool
    write_verified: bool

    @property
    def header_len(self) -> int:
        return self.starts[-1][1]


AIR = Model(
    "air",
    "Air (gen 1)",
    0x0424,
    0x0423,
    ROOT / "firmware" / "07.1.02.387_20240428.bin",
    air_build.STOCK_SHA256.lower(),
    "07.1.02.387_20240428",
    ((0, 24),),
    False,
    True,
)
AIR2 = Model(
    "air2",
    "Air 2",
    0x0428,
    0x0427,
    ROOT / "firmware" / "air2" / "09.1.00.180_20240507.bin",
    air2_build.STOCK_SHA256.lower(),
    air2_build.EXPECT_VERSION.decode(),
    ((0, 42), (42, 64)),
    True,
    True,
)
AIR2_PRO = Model(
    "air2pro",
    "Air 2 Pro",
    0x0432,
    0x0431,
    AIR2.stock,
    AIR2.stock_sha256,
    AIR2.version,
    AIR2.starts,
    True,
    True,
)
MODELS = (AIR, AIR2, AIR2_PRO)
PID_TO_MODEL = {pid: model for model in MODELS for pid in (model.app_pid, model.boot_pid)}


@dataclass(frozen=True)
class KnownImage:
    label: str
    models: frozenset[str]


KNOWN_IMAGES = {
    AIR.stock_sha256: KnownImage("Air stock 07.1.02.387_20240428", frozenset({"air"})),
    air_build.OUTPUT_SHA256.lower(): KnownImage(
        "Air public update output", frozenset({"air"})
    ),
    AIR2.stock_sha256: KnownImage(
        "Air 2 / Air 2 Pro stock 09.1.00.180_20240507",
        frozenset({"air2", "air2pro"}),
    ),
    air2_build.OUTPUT_SHA256.lower(): KnownImage(
        "Air 2 / Air 2 Pro public target-converter output",
        frozenset({"air2", "air2pro"}),
    ),
}

@dataclass(frozen=True)
class ImageInfo:
    sha256: str
    label: str
    models: frozenset[str]
    size: int
    crc: int
    crc_endian: str
    name: str
    header_len: int
    transmit_count: int
    wire_transmit_count: int


@dataclass(frozen=True)
class Connection:
    model: Model
    pid: int
    path: bytes | str
    iface: int
    serial: str

    @property
    def mode(self) -> str:
        return "APP" if self.pid == self.model.app_pid else "BOOT"


def _counts(header_len: int, size: int) -> tuple[int, int]:
    payload = size - header_len
    if payload < 0:
        raise ValueError(f"image is shorter than its {header_len}-byte header")
    logical = (payload + CHUNK - 1) // CHUNK
    wire = logical + (1 if payload % CHUNK else 0)
    return logical, wire


def check_image(data: bytes) -> ImageInfo:
    """Validate the container and require an exact reviewed SHA-256."""
    if len(data) == air_build.SIZE:
        builder, header_len, crc_endian = air_build, air_build.HDR_LEN, "BE"
        format_models = frozenset({"air"})
    elif len(data) == air2_build.SIZE:
        builder, header_len, crc_endian = air2_build, air2_build.HDR_LEN, "LE"
        format_models = frozenset({"air2", "air2pro"})
    else:
        raise ValueError(
            f"unexpected MCU image size {len(data)}; expected "
            f"{air_build.SIZE} (Air) or {air2_build.SIZE} (Air 2 family)"
        )
    try:
        builder.validate_container(data, "MCU image")
    except SystemExit as exc:
        raise ValueError(str(exc).removeprefix("ERROR: ")) from exc

    header = builder.head(data)
    stored_crc = header["stored_crc"]
    name = header["name"] if builder is air_build else header["version"].decode()

    sha = hashlib.sha256(data).hexdigest()
    known = KNOWN_IMAGES.get(sha)
    if known is None:
        raise ValueError(
            "image passes its container checks but is not a reviewed stock/public-output SHA-256:\n"
            f"  {sha}\n"
            "There is no --force option. Rebuild the published output with its model builder."
        )
    if not known.models <= format_models:
        raise ValueError("known-image model set does not match the detected container format")

    logical, wire = _counts(header_len, len(data))
    return ImageInfo(
        sha,
        known.label,
        known.models,
        len(data),
        stored_crc,
        crc_endian,
        name,
        header_len,
        logical,
        wire,
    )


def print_image_info(source: str, info: ImageInfo) -> None:
    names = ", ".join(next(m.name for m in MODELS if m.key == key) for key in sorted(info.models))
    print(f"  source       : {source}")
    print(f"  whitelist    : {info.label} [OK]")
    print(f"  model        : {names}")
    print(f"  size/header  : {info.size} B / {info.header_len} B [OK]")
    print(f"  name/version : {info.name}")
    print(f"  CRC ({info.crc_endian})     : 0x{info.crc:08X} [OK]")
    print(f"  SHA-256      : {info.sha256} [OK]")
    print(
        f"  TRANSMIT     : {info.transmit_count} logical / "
        f"{info.wire_transmit_count} wire packets"
    )


def _enumerate_xreal() -> list[dict]:
    entries: list[dict] = []
    for vendor_id in XREAL_VIDS:
        entries.extend(hid.enumerate(vendor_id, 0))
    return entries


def _device_key(entry: dict) -> tuple[int, int, str]:
    return (
        int(entry.get("vendor_id", 0)),
        int(entry.get("product_id", 0)),
        str(entry.get("serial_number") or "(no serial)"),
    )


def _describe_devices(entries: list[dict]) -> str:
    rows = []
    for vid, pid, serial in sorted({_device_key(entry) for entry in entries}):
        products = sorted(
            {
                str(entry.get("product_string") or "?")
                for entry in entries
                if _device_key(entry) == (vid, pid, serial)
            }
        )
        rows.append(f"{vid:04X}:{pid:04X} product={','.join(products)!r}")
    return "; ".join(rows) or "none"


def unique_connection() -> Connection:
    """Require one supported Air-family device and no other XREAL/Nreal HID."""
    entries = _enumerate_xreal()
    target = [
        entry
        for entry in entries
        if entry.get("vendor_id") == VID and int(entry.get("product_id", 0)) in PID_TO_MODEL
    ]
    other = [entry for entry in entries if entry not in target]
    if other:
        raise RuntimeError(
            "another or unsupported XREAL/Nreal HID device is connected; disconnect it first: "
            + _describe_devices(other)
        )
    if not target:
        raise RuntimeError(
            "Air / Air 2 / Air 2 Pro APP or BOOT was not found (VID 0x3318)"
        )

    pids = {int(entry["product_id"]) for entry in target}
    if len(pids) != 1:
        raise RuntimeError("multiple APP/BOOT products are visible: " + _describe_devices(target))
    pid = next(iter(pids))
    model = PID_TO_MODEL[pid]

    serials = {str(entry.get("serial_number")) for entry in target if entry.get("serial_number")}
    if len(serials) > 1:
        raise RuntimeError("multiple glasses are connected")

    if pid == model.app_pid:
        control = [entry for entry in target if entry.get("interface_number") == CTRL_IF]
        if len(control) != 1:
            raise RuntimeError(
                f"{model.name} APP control IF{CTRL_IF} is not unique; interfaces="
                + repr(sorted(entry.get("interface_number") for entry in target))
            )
        selected = control[0]
    else:
        if len(target) != 1:
            raise RuntimeError(
                f"{model.name} BOOT PID 0x{pid:04X} must expose one HID path; "
                f"found {len(target)}"
            )
        selected = target[0]

    return Connection(
        model,
        pid,
        selected["path"],
        int(selected.get("interface_number", -1)),
        str(selected.get("serial_number") or ""),
    )


def wait_for(model: Model, pid: int, timeout: float) -> Connection:
    end = time.monotonic() + timeout
    last_error = "device not present"
    while time.monotonic() < end:
        if hid.enumerate(VID, pid):
            try:
                connection = unique_connection()
            except RuntimeError as exc:
                last_error = str(exc)
            else:
                if connection.model == model and connection.pid == pid:
                    return connection
        time.sleep(0.02)
    raise RuntimeError(
        f"{model.name} PID 0x{pid:04X} did not become ready within "
        f"{timeout:.1f}s ({last_error})"
    )


class Dev:
    def __init__(self, connection: Connection):
        self.connection = connection
        self.h = hid.device()
        self.h.open_path(connection.path)

    def request(self, msgid: int, payload: bytes = b"", timeout: float = 16.0) -> dict:
        try:
            written = self.h.write(bytes([0]) + cmd_build(msgid, payload))
        except OSError as exc:
            raise RuntimeError(f"op{msgid} write failed: {exc}") from exc
        if written <= 0:
            raise RuntimeError(f"op{msgid} write returned {written}")

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                raw = self.h.read(64, 200)
            except OSError as exc:
                raise RuntimeError(f"op{msgid} response handle disconnected: {exc}") from exc
            if not raw:
                continue
            response = parse_rsp(bytes(raw))
            if response and response["msgid"] == msgid:
                return response
        raise RuntimeError(f"op{msgid} had no response within {timeout:.1f}s")

    def step(self, label: str, msgid: int, payload: bytes = b"") -> dict:
        response = self.request(msgid, payload)
        if response["status"] != 0:
            raise RuntimeError(
                f"{label} (op{msgid}) rejected: status={response['status']} (required 0)"
            )
        return response

    def send(self, msgid: int, payload: bytes = b"") -> None:
        """Fire-and-forget an operation that immediately re-enumerates Air."""
        try:
            written = self.h.write(bytes([0]) + cmd_build(msgid, payload))
        except OSError:
            return
        if written <= 0:
            raise RuntimeError(f"op{msgid} write returned {written}")

    def app_version(self) -> str:
        if self.connection.mode != "APP":
            raise RuntimeError("op38 version reads are disabled in BOOT mode")
        response = self.step("R_MCU_APP_FW_VERSION", R_MCU_APP_FW_VERSION)
        return response["payload"].split(b"\0", 1)[0].decode("ascii", "replace").strip()

    def close(self) -> None:
        try:
            self.h.close()
        except Exception:
            pass


def _open(connection: Connection, retries: int = 12) -> Dev:
    last: Exception | None = None
    for _ in range(retries):
        try:
            return Dev(connection)
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    raise RuntimeError(
        f"cannot open {connection.model.name} PID 0x{connection.pid:04X} "
        f"IF{connection.iface}: {last}"
    )


def print_connection(connection: Connection) -> str | None:
    print(
        f"  {connection.model.name}: PID 0x{connection.pid:04X}, {connection.mode}, "
        f"IF{connection.iface}"
    )
    if connection.mode == "BOOT":
        print("  BOOT detected: version read skipped; byte-exact stock recovery only.")
        return None

    dev = _open(connection)
    try:
        version = dev.app_version()
    finally:
        dev.close()
    print(f"  MCU op38 version: {version!r}")
    return version


def _transfer_from_boot(connection: Connection, image: bytes, info: ImageInfo) -> None:
    model = connection.model
    dev = _open(connection)
    try:
        print(
            f"  BOOT ready: PID 0x{connection.pid:04X}, IF{connection.iface}; "
            "sending START immediately"
        )
        for start, end in model.starts:
            dev.step(f"START[{start}:{end}]", START, image[start:end])
            print(f"  START(63) [{start}:{end}] ack status=0")

        offset = model.header_len
        logical_packet = 0
        wire_packet = 0
        while offset < len(image):
            end = min(offset + CHUNK, len(image))
            dev.step("TRANSMIT", TRANSMIT, image[offset:end])
            wire_packet += 1

            if end == len(image) and end - offset < CHUNK:
                dev.step("TRANSMIT final repeat", TRANSMIT, image[offset:end])
                wire_packet += 1

            offset = end
            logical_packet += 1
            if logical_packet % 100 == 0 or offset == len(image):
                print(
                    f"\r  TRANSMIT(64) {offset}/{len(image)} B "
                    f"({offset * 100.0 / len(image):.0f}%, "
                    f"data {logical_packet}/{info.transmit_count}, "
                    f"wire {wire_packet}/{info.wire_transmit_count})",
                    end="",
                    flush=True,
                )
        if wire_packet != info.wire_transmit_count:
            raise RuntimeError(
                f"internal op64 plan mismatch: sent {wire_packet}, "
                f"expected {info.wire_transmit_count}"
            )
        print("\n  TRANSMIT complete")

        dev.step("FINISH", FINISH)
        print("  FINISH(65) ack status=0 - bootloader accepted the container")
        dev.step("JUMP_TO_APP", JUMP_TO_APP)
        print("  JUMP_TO_APP(66) ack status=0")
    finally:
        dev.close()


def flash(image: bytes, info: ImageInfo, initial: Connection) -> None:
    model = initial.model
    if not model.write_verified:
        raise RuntimeError(f"writing {model.name} is disabled")
    if check_image(image) != info or model.key not in info.models:
        raise RuntimeError("image validation no longer matches the selected model")
    _validate_stock_recovery(model)
    current = unique_connection()
    if (current.model, current.pid) != (model, initial.pid) or (
        initial.serial and current.serial != initial.serial
    ):
        raise RuntimeError("the connected glasses changed before the write")
    initial = current
    if initial.mode == "APP":
        app = _open(initial)
        try:
            version = app.app_version()
        finally:
            app.close()
        if version != model.version:
            raise RuntimeError(
                f"connected MCU version {version!r} is not the reviewed {model.version!r}"
            )
    if initial.mode == "BOOT":
        if info.sha256 != model.stock_sha256:
            raise RuntimeError(
                f"{model.name} is already in BOOT. Only its byte-exact stock "
                "image may be written for interrupted-update recovery."
            )
        print("\n=== STOCK RECOVERY FROM EXISTING BOOT ===")
        print("  PREPARE/JUMP and BOOT op38 are skipped.")
        _transfer_from_boot(initial, image, info)
    else:
        print(f"\n=== ENTER {model.name.upper()} BOOTLOADER ===")
        app = _open(initial)
        try:
            app.step("PREPARE", PREPARE)
            print("  PREPARE(62) ack status=0")
            if model.jump_ack:
                app.step("JUMP_TO_BOOT", JUMP_TO_BOOT)
                print("  JUMP_TO_BOOT(68) ack status=0")
            else:
                app.send(JUMP_TO_BOOT)
                print("  JUMP_TO_BOOT(68) sent (no reply expected)")
        finally:
            app.close()

        print(f"  waiting for {model.name} BOOT PID 0x{model.boot_pid:04X} ...")
        boot = wait_for(model, model.boot_pid, 8.0)
        _transfer_from_boot(boot, image, info)

    print(f"\n=== WAIT FOR {model.name.upper()} APP ===")
    app_state = wait_for(model, model.app_pid, 15.0)
    time.sleep(0.3)
    app = _open(app_state)
    try:
        version = app.app_version()
    finally:
        app.close()
    if version != model.version:
        raise RuntimeError(
            f"APP returned but op38 version is {version!r}, expected {model.version!r}"
        )
    print(f"  APP PID 0x{model.app_pid:04X} returned; op38 version={version!r}")
    print("  Note: stock and public modified outputs intentionally share this version.")


def _validate_stock_recovery(model: Model) -> None:
    if not model.stock.exists():
        raise ValueError(f"stock recovery image is missing: {model.stock}")
    info = check_image(model.stock.read_bytes())
    if info.sha256 != model.stock_sha256 or model.key not in info.models:
        raise ValueError(f"stock recovery image does not match {model.name}")


def self_test() -> None:
    assert len(PID_TO_MODEL) == len(MODELS) * 2
    assert AIR.header_len == 24 and AIR.starts == ((0, 24),)
    assert AIR2.header_len == 64 and AIR2.starts == ((0, 42), (42, 64))
    assert AIR2_PRO.write_verified and AIR2_PRO.stock == AIR2.stock
    assert KNOWN_IMAGES[AIR2.stock_sha256].models == frozenset({"air2", "air2pro"})
    assert KNOWN_IMAGES[air2_build.OUTPUT_SHA256.lower()].models == frozenset(
        {"air2", "air2pro"}
    )
    assert KNOWN_IMAGES[air_build.OUTPUT_SHA256.lower()].models == frozenset({"air"})
    assert _counts(24, 153_888) == (3664, 3665)
    assert _counts(64, 151_160) == (3598, 3599)
    assert len(cmd_build(PREPARE)) == 64
    assert len(cmd_build(START, bytes(42))) == 64
    print("  Air       : 24-byte START, 3664 logical / 3665 wire op64 [OK]")
    print("  Air 2     : 42+22-byte START, 3598 logical / 3599 wire op64 [OK]")
    print("  Air 2 Pro : separate PIDs, shared Air 2 images and wire profile [OK]")
    print("  framing   : 64-byte reports [OK]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XREAL Air-family MCU writer (default is read-only)"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", "-i", help="inspect/use a reviewed stock or public output")
    source.add_argument(
        "--restore",
        action="store_true",
        help="use the connected model's official stock recovery image",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate --image without enumerating/opening any USB device",
    )
    parser.add_argument("--flash", action="store_true", help="actually write the selected image")
    parser.add_argument("--self-test", action="store_true", help="check model transfer plans")
    args = parser.parse_args()

    if args.self_test:
        if args.image or args.restore or args.verify_only or args.flash:
            parser.error("--self-test cannot be combined with other options")
        print("=== MCU FLASHER SELF-TEST ===")
        self_test()
        return
    if args.verify_only and not args.image:
        parser.error("--verify-only requires --image")
    if args.verify_only and args.flash:
        parser.error("--verify-only and --flash are mutually exclusive")
    if args.flash and not (args.image or args.restore):
        parser.error("--flash requires --image or --restore")

    if args.verify_only:
        path = Path(args.image)
        print(f"=== MCU IMAGE VERIFICATION: {path} ===")
        try:
            info = check_image(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print_image_info(str(path), info)
        print("\nVERIFY-ONLY complete. USB was not enumerated/opened; nothing was sent.")
        return

    print("=== UNIQUE DEVICE CHECK ===")
    try:
        connection = unique_connection()
        version = print_connection(connection)
    except (OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    path = connection.model.stock if args.restore else (Path(args.image) if args.image else None)
    if path is None:
        print("\nNo image selected. Read-only status check complete.")
        return
    try:
        image = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read image {path}: {exc}") from exc

    print(f"\n=== MCU IMAGE VERIFICATION: {path} ===")
    try:
        info = check_image(image)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print_image_info(str(path), info)

    model = connection.model
    if model.key not in info.models:
        raise SystemExit(
            "\nMODEL/IMAGE MISMATCH\n"
            f"  connected: {model.name} (PID 0x{connection.pid:04X})\n"
            f"  image    : {info.label}\n"
            "Writing another model's MCU image could break the glasses."
        )
    if info.header_len != model.header_len:
        raise SystemExit("image header and connected-model transfer profile disagree")
    if connection.mode == "BOOT" and info.sha256 != model.stock_sha256:
        raise SystemExit(
            f"{model.name} is already in BOOT; only its byte-exact stock image "
            "may be selected for recovery"
        )

    print("\n=== PLAN ===")
    starts = " + ".join(f"START(63)[{a}:{b}]" for a, b in model.starts)
    prefix = (
        "already BOOT -> "
        if connection.mode == "BOOT"
        else "PREPARE(62) -> JUMP_TO_BOOT(68) -> "
    )
    print(f"  {prefix}{starts}")
    print(
        f"  -> TRANSMIT(64) x{info.wire_transmit_count} -> "
        "FINISH(65) -> JUMP_TO_APP(66)"
    )
    if not model.write_verified:
        print(f"  {model.name} is identified, but public MCU writing is not hardware-verified.")

    if not args.flash:
        print("\nDRY RUN complete. No update command was sent; nothing was written.")
        print("To write, add --flash.")
        return
    if not model.write_verified:
        raise SystemExit(
            f"writing {model.name} is disabled until this exact public procedure is "
            "hardware-verified"
        )
    if connection.mode == "APP" and version != model.version:
        raise SystemExit(
            f"connected MCU version {version!r} is not the reviewed {model.version!r}; refusing"
        )

    try:
        _validate_stock_recovery(model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"\nStock recovery verified: {model.stock}")

    try:
        current = unique_connection()
    except RuntimeError as exc:
        raise SystemExit(f"final device check failed: {exc}") from exc
    if (current.model, current.pid) != (connection.model, connection.pid) or (
        connection.serial and current.serial != connection.serial
    ):
        raise SystemExit("the connected glasses changed after validation; refusing to write")
    connection = current
    print(f"Do not disconnect the cable until APP PID 0x{model.app_pid:04X} returns.")

    try:
        flash(image, info, connection)
    except Exception as exc:
        print(f"\nWRITE FAILED: {exc}")
        print("Leave the cable connected and inspect with:")
        print("  python xreal/mcu_flash.py")
        print("If the BOOT PID is present, recover stock with:")
        print("  python xreal/mcu_flash.py --restore --flash")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
