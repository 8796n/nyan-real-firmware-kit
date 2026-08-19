#!/usr/bin/env python3
r"""Write DP bridge firmware (DP7911) to XREAL glasses over USB HID.

The same path restores a stock image, which is what makes this recoverable.

PROVENANCE
    Ported from the vendor's own WebHID updater (xreal-protocol.js /
    dp_tool.html), not guessed:
      framing        xreal-protocol.js cmdBuild / parseRsp / isAck
      procedure      dp_tool.html flashDp() + edid-tools.js planDpChunks()
      pre-write gate dp_tool.html loadFw(): isDp / containerOk / bank0Ok / mismatch
    Message ids: PREPARE=110 (0x6E) START=111 (0x6F) TRANSMIT=112 (0x70)
    FINISH=113 (0x71). All four are implemented in the Air MCU firmware.

FRAME (64-byte report, report id 0)
    [0]=0xFD  [1:5]=CRC32-LE  [5:7]=len-LE (=17+payload)  [15:17]=msgId-LE
    [22:]=payload.  The CRC covers [5 : 5+len).  Payload is at most 42 bytes.
    Response: msgId=[15]|[16]<<8, status=[22], ack when status is 0 or 250.

CHUNK PLAN
    START(111)     fw[0:42]
    START(111)     fw[42:64]      the first 64 bytes, the container header,
                                  are split across two frames
    TRANSMIT(112)  fw[64:] in 42-byte pieces
    FINISH(113)    the MCU verifies the container CRC; a mismatch returns 5

RISKS -- read these
  * Writing a project code that does not match the connected model can destroy
    the glasses. `1140` is a shared payload across air / air2 / flora / p55 and
    only the header's project code differs, so the file name tells you nothing.
    This tool refuses on mismatch. Do not defeat that check.

  * If the bank0 commit tag at [0x38] does not match, the DP7911 boot rejects
    bank0 and falls back to an internal image: version reads 1109, the monitor
    name becomes "nreal air", the refresh rate sticks at 60 Hz and mode
    switching stops working. This is recoverable -- write a good image again
    with this same tool.

  * No replug is needed for a normal write. The bridge restarts itself after
    FINISH and the new image is live immediately.

  * The exception is a failed write: a non-ack FINISH, a timeout, or an
    interrupted transfer. PREPARE does not reset the header count and the SPI
    write offset, so retrying inside the same MCU power session is unsafe.
    Only in that case, unplug and replug to reset the MCU before retrying.

  * Repeating a successful write is safe. Nine consecutive writes to an Air
    without a single replug all returned a FINISH ack and reported version
    1140.

USAGE
  python dp_flash.py                        identify and read the version only
  python dp_flash.py --image FILE           inspect and show the chunk plan
  python dp_flash.py --image FILE --flash   actually write it
  python dp_flash.py --restore --flash      write the stock image back
  python dp_flash.py --self-test            check framing against the reference
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import hid
import container as integrity
from glasses import VID, CTRL_IF, PIDS, build_fd

STOCK = ROOT / "firmware" / "1140"
STOCK_SHA256 = "66a28c7be1842d6837c68a5586cb0465099787f421427be0cbe9691c858837da"

# ---- protocol constants (xreal-protocol.js) ---------------------------------
OFF_CRC, OFF_LEN, OFF_MSGID, OFF_PAYLOAD = 1, 5, 15, 22
REPORT_SIZE = 64
MAGIC = 0xFD
MAX_PAYLOAD = REPORT_SIZE - OFF_PAYLOAD          # 42
ACK_STATUS = (0, 250)                            # 250 = 0xFA reportCheck

PREPARE, START, TRANSMIT, FINISH = 110, 111, 112, 113
R_DP_FW_VERSION = 22

# dp_tool.html PID_TO_PROJECT / PROJECTS
PID_TO_PROJECT = {
    0x0424: 0x0700, 0x0423: 0x0700,              # Air (APP/BOOT)
    0x0432: 0x0900, 0x0431: 0x0900,              # Air 2 Pro
    0x0428: 0x0900, 0x0427: 0x0900,              # Air 2 (inferred)
    0x0425: 0x1200, 0x0426: 0x1200,              # Air 2 Ultra
    0x0435: 0x1500, 0x0436: 0x1500,              # XREAL One
    0x0437: 0x1500, 0x0438: 0x1500,              # XREAL One Pro
    0x0441: 0x1900, 0x0442: 0x1900,              # xbx a01+
}
PROJECTS = {0x0700: "air (Air)", 0x0900: "p55 (Air 2 / Air 2 Pro)",
            0x1200: "flora (Air 2 Ultra)", 0x1500: "gf,gina (One / One Pro)",
            0x1900: "helen (xbx a01+)"}


def cmd_build(msgid: int, payload: bytes = b"") -> bytes:
    """Port of xreal-protocol.js cmdBuild. Always returns exactly 64 bytes."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload %d > %d" % (len(payload), MAX_PAYLOAD))
    n = bytearray(REPORT_SIZE)
    n[0] = MAGIC
    n[OFF_MSGID] = msgid & 0xFF
    n[OFF_MSGID + 1] = (msgid >> 8) & 0xFF
    ln = 17 + len(payload)
    n[OFF_PAYLOAD:OFF_PAYLOAD + len(payload)] = payload
    struct.pack_into("<H", n, OFF_LEN, ln)
    crc = zlib.crc32(bytes(n[OFF_LEN:OFF_LEN + ln])) & 0xFFFFFFFF
    struct.pack_into("<I", n, OFF_CRC, crc)
    return bytes(n)


def parse_rsp(b: bytes) -> dict | None:
    if not b or len(b) < OFF_PAYLOAD + 1 or b[0] != MAGIC:
        return None
    return dict(msgid=b[OFF_MSGID] | (b[OFF_MSGID + 1] << 8),
                status=b[OFF_PAYLOAD],
                payload=bytes(b[OFF_PAYLOAD + 1:]))


def plan_chunks(n: int) -> list[tuple[str, int, int, int]]:
    """Port of edid-tools.js planDpChunks. Yields (label, msgid, start, end)."""
    steps = []
    a = min(42, n)
    steps.append(("START", START, 0, a))
    if n > 42:
        l = min(22, n - a)
        steps.append(("START", START, a, a + l))
        a += l
    while a < n:
        e = min(a + 42, n)
        steps.append(("TRANSMIT", TRANSMIT, a, e))
        a = e
    return steps


class Glasses:
    def __init__(self):
        self.pid = None
        self.h = None
        for pid in PIDS:
            paths = {d["interface_number"]: d["path"] for d in hid.enumerate(VID, pid)}
            if CTRL_IF in paths:
                self.h = hid.device()
                self.h.open_path(paths[CTRL_IF])
                self.pid = pid
                return
        sys.exit("XREAL control interface MI_04 not found. Plug the glasses "
                 "directly into this PC.")

    @property
    def name(self):
        return PIDS.get(self.pid, "unknown 0x%04X" % self.pid)

    @property
    def project(self):
        return PID_TO_PROJECT.get(self.pid)

    def request(self, msgid: int, payload: bytes = b"", timeout=16.0) -> dict:
        self.h.write(bytes([0x00]) + cmd_build(msgid, payload))
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self.h.read(REPORT_SIZE, 200)
            except OSError as e:
                raise RuntimeError("HID read error: %s" % e)
            if not r:
                continue
            p = parse_rsp(bytes(r))
            if p and p["msgid"] == msgid:
                return p
        raise RuntimeError("op%d did not answer within %.0f s" % (msgid, timeout))

    def version(self) -> str:
        try:
            p = self.request(R_DP_FW_VERSION, timeout=3.0)
        except RuntimeError:
            return "(read failed)"
        return p["payload"].split(b"\x00")[0].decode("ascii", "replace").strip()

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass


def check_image(img: bytes, dev: Glasses | None) -> None:
    """Decide whether this image may be written, on dp_tool.html loadFw() terms."""
    h = integrity.head(img)
    if h["project"] not in PROJECTS or h["fwtype"] != 2:
        sys.exit("not a DP container (projectCode 0x%04X / fwType %d)"
                 % (h["project"], h["fwtype"]))
    if integrity.crc_container(img[8:8 + h["length"]]) != h["stored_crc"]:
        sys.exit("container CRC mismatch. Do not write this image.")
    if not integrity.bank0_ok(img):
        sys.exit("bank0 tag mismatch. Writing this would drop the bridge into the "
                 "1109 fallback.\n       Rebuild the image with its builder.")
    print("  image     : %s / %d B / projectCode 0x%04X = %s"
          % (h["name"], len(img), h["project"], PROJECTS[h["project"]]))
    print("              container CRC 0x%08X [OK]   bank0 tag 0x%02X [OK]"
          % (h["stored_crc"], img[integrity.TAG_OFF]))
    print("              sha256 %s" % hashlib.sha256(img).hexdigest())
    if dev is not None and dev.project is not None and dev.project != h["project"]:
        sys.exit("\nPROJECT CODE MISMATCH\n"
                 "  connected: %s (PID 0x%04X) is 0x%04X = %s\n"
                 "  image    : 0x%04X = %s\n"
                 "Writing this would break the glasses. Aborting."
                 % (dev.name, dev.pid, dev.project, PROJECTS.get(dev.project, "?"),
                    h["project"], PROJECTS[h["project"]]))


def flash(dev: Glasses, img: bytes) -> None:
    steps = plan_chunks(len(img))
    print("\n=== writing (%d chunks) ===" % (len(steps) + 2))

    def step(label, msgid, payload=b""):
        p = dev.request(msgid, payload)
        if p["status"] not in ACK_STATUS:
            raise RuntimeError("%s (op%d) was not acked, status=%d" % (label, msgid, p["status"]))
        return p

    step("PREPARE", PREPARE)
    print("  PREPARE(110) ack")
    done = 0
    for name, msgid, a, b in steps:
        step(name, msgid, img[a:b])
        done = b
        if name == "TRANSMIT" and (done % 4200 < 42 or done == len(img)):
            print("\r  TRANSMIT(112) %d / %d B (%.0f%%)"
                  % (done, len(img), done * 100.0 / len(img)), end="", flush=True)
    print("\n  START/TRANSMIT complete")
    step("FINISH", FINISH)
    print("  FINISH(113) ack: the MCU verified the container CRC")


def post_check(expect_hint: str) -> None:
    print("\n=== waiting 4 s and re-enumerating ===")
    time.sleep(4.0)
    try:
        dev = Glasses()
    except SystemExit:
        print("  HID did not come back. Unplug and replug the cable.")
        return
    v = dev.version()
    dev.close()
    print("  DP firmware version = %r  (%s)" % (v, expect_hint))
    if v.strip() == "1109":
        print("  Dropped into the 1109 fallback: bank0 was rejected.")
        print("    restore stock: python xreal/dp_flash.py --restore --flash")
    print("\n  The bridge restarted after FINISH, so the new image is already live.")
    print("    python xreal/display.py                 current display mode")
    print("    python xreal/edid_dump.py --save after_flash")


def self_test() -> None:
    """Check that cmd_build matches glasses.build_fd(msgid, PAD6+payload, 0, 0)."""
    ok = True
    for msgid, pl in ((PREPARE, b""), (START, bytes(range(42))), (TRANSMIT, b"\xaa" * 42),
                      (FINISH, b""), (R_DP_FW_VERSION, b"")):
        mine = cmd_build(msgid, pl)
        theirs = build_fd(msgid, b"\x00" * 6 + pl, 0, 0).ljust(REPORT_SIZE, b"\x00")
        same = mine == theirs
        ok &= same
        print("  op%-4d payload %2dB : %s" % (msgid, len(pl), "match" if same else "MISMATCH"))
        if not same:
            print("    cmd_build : %s" % mine.hex())
            print("    build_fd  : %s" % theirs.hex())
    print("  -> %s" % ("cmd_build is byte-identical to build_fd" if ok else "mismatches found"))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Write DP bridge firmware. Sends nothing unless --flash is given.")
    ap.add_argument("--image", "-i", default=None)
    ap.add_argument("--restore", action="store_true",
                    help="write back the stock image from firmware/1140")
    ap.add_argument("--flash", action="store_true", help="actually send it")
    ap.add_argument("--after-power-cycle", action="store_true",
                    help="records that the MCU was reset after a failed write; "
                         "not needed before a normal write")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        print("=== framing self-test ===")
        return self_test()

    dev = Glasses()
    print("=== connected glasses ===")
    print("  %s (VID 0x%04X / PID 0x%04X) projectCode 0x%04X"
          % (dev.name, VID, dev.pid, dev.project or 0))
    print("  DP firmware version = %r" % dev.version())
    path = STOCK if a.restore else (Path(a.image) if a.image else None)
    if path is None:
        print("\nPass --image to inspect an image, or --restore to write stock back.")
        dev.close()
        return

    img = path.read_bytes()
    print("\n=== inspecting: %s ===" % path)
    check_image(img, dev)
    if a.restore and hashlib.sha256(img).hexdigest() != STOCK_SHA256:
        dev.close()
        sys.exit("--restore target does not match the stock sha256. Aborting.")

    steps = plan_chunks(len(img))
    print("\n=== chunk plan ===")
    print("  PREPARE(110) -> START(111) x2 (header) -> TRANSMIT(112) x%d -> FINISH(113)"
          % sum(1 for s in steps if s[0] == "TRANSMIT"))
    print("  %d packets total / %d B payload" % (len(steps) + 2, len(img)))

    if not a.flash:
        print("\nNothing was sent. Add --flash to actually write it.")
        print("  The bridge restarts itself after a successful FINISH, so no replug")
        print("  is needed before or after.")
        dev.close()
        return

    if not STOCK.exists():
        dev.close()
        sys.exit("stock image %s not found. Refusing to write without a recovery "
                 "path in place." % STOCK)

    print("\n  recovery path: python xreal/dp_flash.py --restore --flash")
    try:
        flash(dev, img)
    except RuntimeError as e:
        print("\nWRITE FAILED: %s" % e)
        print("  bank0 and the MCU transfer offset may both be left incomplete.")
        print("  Unplug and replug to reset the MCU before retrying. This is the one")
        print("  case where that is required.")
        print("  recovery: python xreal/dp_flash.py --restore --flash --after-power-cycle")
        dev.close()
        sys.exit(1)
    dev.close()
    post_check("stock reads '1140'; the fallback reads '1109'")


if __name__ == "__main__":
    main()
