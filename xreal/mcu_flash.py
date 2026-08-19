#!/usr/bin/env python3
r"""Write MCU application firmware to XREAL Air glasses over USB HID.

The same path restores a stock image.

PROVENANCE
    Ported from the vendor's own web updater; the sequence below was recovered
    from its upgradeInMcu implementation:

      62 W_UPDATE_MCU_APP_FW_PREPARE    empty payload
      68 W_MCU_APP_JUMP_TO_BOOT         empty payload
         -> the device re-enumerates with the BOOT product id
      63 W_UPDATE_MCU_APP_FW_START      fw[0:24], exactly the container header
      64 W_UPDATE_MCU_APP_FW_TRANSMIT   fw[24:] in 42-byte pieces
      65 W_UPDATE_MCU_APP_FW_FINISH     empty payload
      66 W_BOOT_JUMP_TO_APP             empty payload

    Here an ack means status == 0 only, which is stricter than the DP side
    (0 or 250). The host does not compute a whole-file CRC; the bootloader
    verifies it at FINISH.

WHY THIS IS RECOVERABLE
    The bootloader lives separately from the application, and only the
    application area is rewritten. The official procedure itself drops into
    the bootloader to do the write, so even an application that will not start
    leaves you with a device that enumerates as PID 0x0423 (Air BOOT), and this
    tool can write a stock image back from there.

    That safety net assumes nothing can damage the bootloader itself. This
    tool only ever sends the application area.

WHAT THE VENDOR TELLS USERS
    * connect exactly one pair of glasses, no other device or adapter
    * do not unplug during the update
    * update the MCU first and the DP bridge second, and finish both
    * the PC display may flicker or go dark during the update

POWER CYCLING
    A normal APP -> BOOT -> APP update needs no physical replug; the MCU
    re-enumerates by itself and the new image is live. Consider a power cycle
    only if the device stops answering after a failed transfer, as part of
    working out what state it is in.

USAGE
  python mcu_flash.py                        show connection state and version
  python mcu_flash.py --image FILE           inspect and show the plan
  python mcu_flash.py --restore              target the stock image
  python mcu_flash.py --restore --flash      actually write stock back
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import hid
from glasses import VID, CTRL_IF, PIDS
from dp_flash import ACK_STATUS, MAX_PAYLOAD, cmd_build, parse_rsp   # same framing

STOCK = ROOT / "firmware" / "07.1.02.387_20240428.bin"
STOCK_SHA256 = "b1784c6d618d3cf6f03d77a93442c3267a425cb2be415e8912539e165645a3e7"
# Matches the version string the device reports, so restoring is idempotent.

APP_PID, BOOT_PID = 0x0424, 0x0423

PREPARE, JUMP_TO_BOOT = 62, 68
START, TRANSMIT, FINISH, JUMP_TO_APP = 63, 64, 65, 66
R_MCU_APP_FW_VERSION = 38

HDR_LEN = 24                 # what START sends: exactly the container header
CHUNK = 42
# [0:4] is not a magic number: it is the CRC-32 of payload[8:] (poly
# 0xF4ACFB13, stored big-endian). The bootloader checks it at FINISH(65), so
# this tool checks it too before sending anything.
sys.path.insert(0, str(HERE))
import container as _integrity


def head(d: bytes) -> dict:
    """Air MCU container: [0:4] CRC-32 BE / [4:8] length (filesize-8) / [8:24] name."""
    crc, length = struct.unpack_from(">I", d, 0)[0], struct.unpack_from("<I", d, 4)[0]
    name = d[8:24].split(b"\0")[0].decode("ascii", "replace")
    return dict(crc=crc, length=length, name=name)


def check_image(d: bytes) -> dict:
    h = head(d)
    if h["length"] + 8 != len(d):
        sys.exit("length field is inconsistent (%d + 8 != %d)" % (h["length"], len(d)))
    if not h["name"].startswith("Air."):
        sys.exit("this image is for another model (name=%r). Air images start "
                 "with 'Air.'" % h["name"])
    calc = _integrity.crc_container(d[8:])
    if h["crc"] != calc:
        sys.exit("container CRC-32 mismatch: stored 0x%08X / computed 0x%08X\n"
                 "       The bootloader would reject this at FINISH. Rebuild the "
                 "image with its builder." % (h["crc"], calc))
    print("  image     : %s / %d B / length field OK" % (h["name"], len(d)))
    print("              container CRC-32 0x%08X [OK]" % h["crc"])
    print("              sha256 %s" % hashlib.sha256(d).hexdigest())
    return h


def _iface_of(pid):
    """Return the interface number to use for this product id.

    APP exposes interfaces 3-6 and control is IF4. The bootloader exposes a
    single interface, IF0, so hard-coding CTRL_IF would miss BOOT entirely.
    """
    ifs = sorted(d["interface_number"] for d in hid.enumerate(VID, pid))
    if not ifs:
        return None
    return CTRL_IF if CTRL_IF in ifs else ifs[0]


class Dev:
    def __init__(self, pid=None, retries=12):
        """Retry briefly: the OS is not always ready the instant a device appears."""
        self.h = None
        self.pid = None
        self.iface = None
        last = None
        for _ in range(retries):
            for p in ([pid] if pid else (APP_PID, BOOT_PID)):
                want = _iface_of(p)
                if want is None:
                    continue
                paths = {x["interface_number"]: x["path"] for x in hid.enumerate(VID, p)}
                try:
                    h = hid.device()
                    h.open_path(paths[want])
                except OSError as e:
                    last = e
                    continue
                self.h, self.pid, self.iface = h, p, want
                return
            time.sleep(0.05)
        raise RuntimeError("no HID device found (VID 0x%04X / PID %s)%s"
                           % (VID, "0x%04X" % pid if pid else "0x0424 or 0x0423",
                              "  last error: %s" % last if last else ""))

    @property
    def mode(self):
        return "APP" if self.pid == APP_PID else ("BOOT" if self.pid == BOOT_PID else "?")

    def send(self, msgid, payload=b""):
        """Send without waiting for a reply, for ops that re-enumerate immediately."""
        try:
            self.h.write(bytes([0x00]) + cmd_build(msgid, payload))
        except OSError:
            pass                       # the device may already be gone; expected

    def request(self, msgid, payload=b"", timeout=16.0):
        try:
            self.h.write(bytes([0x00]) + cmd_build(msgid, payload))
        except OSError as e:
            raise RuntimeError("op%d could not be sent (device gone?): %s" % (msgid, e))
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self.h.read(64, 200)
            except OSError as e:
                # The handle died, most likely a re-enumeration. Let the caller judge.
                raise RuntimeError("op%d handle closed while waiting: %s" % (msgid, e))
            if not r:
                continue
            p = parse_rsp(bytes(r))
            if p and p["msgid"] == msgid:
                return p
        raise RuntimeError("op%d did not answer within %.0f s" % (msgid, timeout))

    def version(self):
        try:
            p = self.request(R_MCU_APP_FW_VERSION, timeout=3.0)
        except RuntimeError:
            return "(read failed)"
        return p["payload"].split(b"\x00")[0].decode("ascii", "replace").strip()

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass


def wait_for(pid, secs=8.0):
    """Wait for that product id to enumerate. Do not assume an interface number.

    Measured: the device disappears about 0.35 s after JUMP_TO_BOOT, BOOT shows
    up at about 1.37 s, and it stays there roughly 15 seconds before returning
    to the application on its own.
    """
    end = time.time() + secs
    while time.time() < end:
        if hid.enumerate(VID, pid):
            return True
        time.sleep(0.02)
    return False


def flash(img: bytes) -> None:
    # Already in BOOT: skip PREPARE and JUMP and go straight to the transfer.
    # This is the recovery path when a broken application left it stuck there.
    already_boot = bool(hid.enumerate(VID, BOOT_PID))
    dev = Dev(BOOT_PID if already_boot else APP_PID)
    print("\n=== writing (currently in %s mode) ===" % dev.mode)

    def step(label, msgid, payload=b""):
        p = dev.request(msgid, payload)
        if p["status"] not in ACK_STATUS or p["status"] != 0:
            raise RuntimeError("%s (op%d) was not acked, status=%d" % (label, msgid, p["status"]))
        return p

    if already_boot:
        print("  Already in BOOT mode. Skipping PREPARE / JUMP_TO_BOOT.")
        print("  bootloader version = %r" % dev.version())
        _transfer(dev, img, step)
        return

    step("PREPARE", PREPARE)
    print("  PREPARE(62) ack")

    # The device disappears right after JUMP_TO_BOOT and comes back as BOOT.
    # Waiting for a reply both fails with OSError and burns the window in which
    # the bootloader accepts a transfer -- it returns to the application if the
    # update does not continue. So fire and forget, then poll immediately.
    dev.send(JUMP_TO_BOOT)
    print("  JUMP_TO_BOOT(68) sent (no reply expected)")
    dev.close()

    print("  waiting for the device to re-enumerate in BOOT mode ...")
    if not wait_for(BOOT_PID, 8.0):
        raise RuntimeError("BOOT (PID 0x%04X) never appeared. If it simply went "
                           "back to APP the device is unharmed." % BOOT_PID)
    dev = Dev(BOOT_PID)
    print("  in BOOT mode (PID 0x%04X / IF%d)" % (dev.pid, dev.iface))
    print("  bootloader version = %r" % dev.version())
    # BOOT stays available for about 15 seconds. Starting the transfer should
    # extend that, but do not do anything else between here and START.

    _transfer(dev, img, step)


def _transfer(dev, img: bytes, step) -> None:
    """The transfer itself, in BOOT mode. BOOT lasts about 15 s: do not dawdle."""
    try:
        step("START", START, img[:HDR_LEN])
        print("  START(63) ack - %d B header sent" % HDR_LEN)
        n = HDR_LEN
        total = len(img)
        while n < total:
            e = min(n + CHUNK, total)
            step("TRANSMIT", TRANSMIT, img[n:e])
            n = e
            if n % 4200 < CHUNK or n == total:
                print("\r  TRANSMIT(64) %d / %d B (%.0f%%)"
                      % (n, total, n * 100.0 / total), end="", flush=True)
        print("\n  TRANSMIT complete")
        step("FINISH", FINISH)
        print("  FINISH(65) ack")
        step("JUMP_TO_APP", JUMP_TO_APP)
        print("  JUMP_TO_APP(66) ack")
    finally:
        dev.close()

    print("\n=== waiting for the device to return to APP mode ===")
    if wait_for(APP_PID, 10.0):
        time.sleep(0.5)
        d2 = Dev(APP_PID)
        print("  back in APP mode. MCU firmware version = %r" % d2.version())
        d2.close()
    else:
        print("  It has not come back to APP. It may still be in BOOT.")
        print("    check with: python xreal/mcu_flash.py")
        print("    if it is in BOOT you can write stock back (--restore --flash)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Write Air MCU application firmware. Sends nothing unless --flash.")
    ap.add_argument("--image", "-i", default=None)
    ap.add_argument("--restore", action="store_true",
                    help="target the stock image %s" % STOCK.name)
    ap.add_argument("--flash", action="store_true", help="actually send it")
    ap.add_argument(
        "--after-power-cycle",
        action="store_true",
        help="records that the device was power cycled after a failed write; "
             "not needed for a normal update",
    )
    a = ap.parse_args()

    print("=== connection state ===")
    try:
        dev = Dev()
        print("  %s (PID 0x%04X) = %s mode" % (PIDS.get(dev.pid, "?"), dev.pid, dev.mode))
        if dev.mode == "APP":
            print("  MCU firmware version = %r" % dev.version())
        else:
            print("  In BOOT mode: the application is not running.")
            print("    write stock back: python xreal/mcu_flash.py --restore --flash")
        dev.close()
    except RuntimeError as e:
        sys.exit("  %s" % e)

    path = STOCK if a.restore else (Path(a.image) if a.image else None)
    if path is None:
        print("\nPass --image or --restore.")
        return
    img = path.read_bytes()
    print("\n=== inspecting: %s ===" % path)
    check_image(img)
    if a.restore and hashlib.sha256(img).hexdigest() != STOCK_SHA256:
        sys.exit("--restore target does not match the stock sha256. Aborting.")

    nchunk = (len(img) - HDR_LEN + CHUNK - 1) // CHUNK
    print("\n=== plan ===")
    print("  PREPARE(62) -> JUMP_TO_BOOT(68) -> [re-enumerate as BOOT] -> START(63, 24B)")
    print("  -> TRANSMIT(64) x%d -> FINISH(65) -> JUMP_TO_APP(66)" % nchunk)
    print("  %d packets total" % (nchunk + 5))

    if not a.flash:
        print("\nNothing was sent. Add --flash to actually write it.")
        print("  Vendor guidance: connect one pair only, do not unplug during the")
        print("  update, and update the MCU first and the DP bridge second.")
        return
    if not STOCK.exists():
        sys.exit("stock image %s not found. Refusing to write without a recovery "
                 "path in place." % STOCK)

    if a.after_power_cycle:
        print("\n  noted: power cycled after a failed write (--after-power-cycle)")
    else:
        print("\n  normal update: no physical replug needed")
    print("  recovery path: python xreal/mcu_flash.py --restore --flash")
    try:
        flash(img)
    except RuntimeError as e:
        print("\nWRITE FAILED: %s" % e)
        print("  Do not unplug yet. Check the state first: python xreal/mcu_flash.py")
        print("  If it reports BOOT mode you can write a stock image back.")
        sys.exit(1)


if __name__ == "__main__":
    main()
