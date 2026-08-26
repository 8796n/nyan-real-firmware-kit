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
    FINISH=113 (0x71). All four are implemented in the verified Air and Air 2
    MCU firmware.

FRAME (64-byte report, report id 0)
    [0]=0xFD  [1:5]=CRC32-LE  [5:7]=len-LE (=17+payload)  [15:17]=msgId-LE
    [22:]=payload.  The CRC covers [5 : 5+len).  Payload is at most 42 bytes.
    Response: msgId=[15]|[16]<<8, status=[22]. Intermediate write acks may
    be 0 or 250; FINISH is successful only when status is 0.

CHUNK PLAN
    START(111)     fw[0:42]
    START(111)     fw[42:64]      the first 64 bytes, the container header,
                                  are split across two frames
    TRANSMIT(112)  fw[64:] in 42-byte pieces
    FINISH(113)    the MCU verifies the container CRC; a mismatch returns 5

RISKS -- read these
  * Writing an image for another model can destroy the glasses. `1140` is a
    shared payload name, so the file name tells you nothing. Project-code
    matching is necessary but not sufficient: Air 2 and Air 2 Pro both use
    0x0900. This writer therefore requires an exact known image SHA for the
    connected PID. Air 2 and Air 2 Pro accept the same reviewed p55 images.

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
from air import build_dp as air_build
from air2 import build_dp as air2_build
from glasses import VID, CTRL_IF, PIDS, build_fd

WRITE_PROFILES = {
    0x0424: dict(
        name="Air (gen 1)",
        project=0x0700,
        stock=ROOT / "firmware" / "1140",
        stock_sha=air_build.STOCK_SHA256,
        output_sha=air_build.OUTPUT_SHA256,
        validate=air_build.validate_container,
    ),
    0x0428: dict(
        name="Air 2",
        project=0x0900,
        stock=ROOT / "firmware" / "air2" / "1140",
        stock_sha=air2_build.STOCK_SHA256,
        output_sha=air2_build.OUTPUT_SHA256,
        validate=air2_build.validate_container,
    ),
}
# Air 2 Pro runs the same reviewed p55 stock/output images; only the USB PID
# and runtime model selection separate it from Air 2.
WRITE_PROFILES[0x0432] = dict(WRITE_PROFILES[0x0428], name="Air 2 Pro")

# One SHA can belong to more than one PID: Air 2 and Air 2 Pro share both images.
KNOWN_IMAGES: dict[str, tuple[set[int], str]] = {}
for _pid, _profile in WRITE_PROFILES.items():
    for _key, _label in (("stock_sha", "official stock"), ("output_sha", "published output")):
        if _profile[_key] is not None:
            KNOWN_IMAGES.setdefault(_profile[_key], (set(), _label))[0].add(_pid)

# ---- protocol constants (xreal-protocol.js) ---------------------------------
OFF_CRC, OFF_LEN, OFF_MSGID, OFF_PAYLOAD = 1, 5, 15, 22
REPORT_SIZE = 64
MAGIC = 0xFD
MAX_PAYLOAD = REPORT_SIZE - OFF_PAYLOAD          # 42
ACK_STATUS = (0, 250)                            # intermediate: 250 = reportCheck

PREPARE, START, TRANSMIT, FINISH = 110, 111, 112, 113
R_DP_FW_VERSION = 22

# dp_tool.html PID_TO_PROJECT / PROJECTS
PID_TO_PROJECT = {
    0x0424: 0x0700, 0x0423: 0x0700,              # Air (APP/BOOT)
    0x0432: 0x0900, 0x0431: 0x0900,              # Air 2 Pro
    0x0428: 0x0900, 0x0427: 0x0900,              # Air 2
    0x0425: 0x1200, 0x0426: 0x1200,              # unsupported project 0x1200
    0x0435: 0x1500, 0x0436: 0x1500,              # XREAL One
    0x0437: 0x1500, 0x0438: 0x1500,              # XREAL One Pro
    0x0441: 0x1900, 0x0442: 0x1900,              # xbx a01+
}
PROJECTS = {0x0700: "air (Air)", 0x0900: "p55 (Air 2 / Air 2 Pro)",
            0x1200: "unsupported project 0x1200", 0x1500: "gf,gina (One / One Pro)",
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
        controls = [d for d in hid.enumerate(VID, 0)
                    if d.get("interface_number") == CTRL_IF]
        if not controls:
            sys.exit("XREAL control interface MI_04 not found. Plug the glasses "
                     "directly into this PC.")
        if len(controls) != 1:
            pids = ", ".join("0x%04X" % int(d.get("product_id", 0)) for d in controls)
            sys.exit("multiple XREAL control devices found (%s). Connect exactly one pair."
                     % pids)
        entry = controls[0]
        pid = int(entry["product_id"])
        if pid not in WRITE_PROFILES:
            sys.exit("unsupported XREAL control device PID 0x%04X; nothing was opened" % pid)
        self.h = hid.device()
        self.h.open_path(entry["path"])
        self.pid = pid

    @property
    def name(self):
        return PIDS.get(self.pid, "unknown 0x%04X" % self.pid)

    @property
    def project(self):
        return PID_TO_PROJECT.get(self.pid)

    def request(self, msgid: int, payload: bytes = b"", timeout=16.0) -> dict:
        try:
            written = self.h.write(bytes([0x00]) + cmd_build(msgid, payload))
        except OSError as e:
            raise RuntimeError("op%d write failed: %s" % (msgid, e)) from e
        if written <= 0:
            raise RuntimeError("op%d write returned %d" % (msgid, written))
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
    """Validate and classify an exact reviewed Air/Air 2 image."""
    try:
        h = integrity.head(img)
    except (IndexError, struct.error):
        sys.exit("not a DP container: header is truncated")
    validators = {0x0700: air_build.validate_container, 0x0900: air2_build.validate_container}
    validate = validators.get(h["project"])
    if validate is None or h["fwtype"] != 2:
        sys.exit("not a supported DP container (projectCode 0x%04X / fwType %d)"
                 % (h["project"], h["fwtype"]))
    validate(img, "image")
    if not integrity.bank0_ok(img):
        sys.exit("bank0 tag mismatch. Writing this would drop the bridge into the "
                 "1109 fallback.\n       Rebuild the image with its builder.")
    digest = hashlib.sha256(img).hexdigest().upper()
    known = KNOWN_IMAGES.get(digest)
    if known is None:
        sys.exit("container checks pass, but SHA-256 is not an exact reviewed "
                 "stock/public-output image:\n       %s" % digest)
    image_pids, image_kind = known
    image_model = " / ".join(WRITE_PROFILES[p]["name"] for p in sorted(image_pids))
    print("  image     : %s / %d B / projectCode 0x%04X = %s"
          % (h["name"], len(img), h["project"], PROJECTS[h["project"]]))
    print("              container CRC 0x%08X [OK]   bank0 tag 0x%02X [OK]"
          % (h["stored_crc"], img[integrity.TAG_OFF]))
    print("              sha256 %s [%s %s]" % (digest, image_model, image_kind))
    if dev is not None and dev.project is not None and dev.project != h["project"]:
        sys.exit("\nPROJECT CODE MISMATCH\n"
                 "  connected: %s (PID 0x%04X) is 0x%04X = %s\n"
                 "  image    : 0x%04X = %s\n"
                 "Writing this would break the glasses. Aborting."
                 % (dev.name, dev.pid, dev.project, PROJECTS.get(dev.project, "?"),
                    h["project"], PROJECTS[h["project"]]))
    if dev is not None and dev.pid in WRITE_PROFILES and dev.pid not in image_pids:
        sys.exit("\nEXACT IMAGE / DEVICE MISMATCH\n"
                 "  connected: %s (PID 0x%04X)\n"
                 "  image    : %s %s\n"
                 "Project code alone is not used as model proof. Aborting."
                 % (dev.name, dev.pid, image_model, image_kind))
def verify_recovery(profile: dict) -> None:
    path = profile["stock"]
    if not path.exists():
        sys.exit("stock image %s not found. Refusing to write without a recovery "
                 "path in place." % path)
    stock = path.read_bytes()
    digest = hashlib.sha256(stock).hexdigest().upper()
    if digest != profile["stock_sha"]:
        sys.exit("stock recovery SHA-256 mismatch for %s:\n"
                 "  expected %s\n  got      %s\nRefusing to write."
                 % (profile["name"], profile["stock_sha"], digest))
    profile["validate"](stock, "stock recovery image")
    if not integrity.bank0_ok(stock):
        sys.exit("stock recovery bank0 tag mismatch. Refusing to write.")
    print("  stock recovery verified: %s / SHA-256 %s" % (path, digest))


def image_approved(profile: dict, digest: str) -> bool:
    return digest in (profile["stock_sha"], profile["output_sha"])


def flash(dev: Glasses, img: bytes) -> None:
    profile = WRITE_PROFILES.get(dev.pid)
    if profile is None:
        raise RuntimeError("writing is disabled for PID 0x%04X" % dev.pid)
    digest = hashlib.sha256(img).hexdigest().upper()
    if not image_approved(profile, digest):
        raise RuntimeError("image SHA-256 is not approved for PID 0x%04X" % dev.pid)
    verify_recovery(profile)
    steps = plan_chunks(len(img))
    print("\n=== writing (%d chunks) ===" % (len(steps) + 2))

    def step(label, msgid, payload=b""):
        p = dev.request(msgid, payload)
        allowed = (0,) if msgid == FINISH else ACK_STATUS
        if p["status"] not in allowed:
            raise RuntimeError("%s (op%d) was not acked, status=%d; expected %s"
                               % (label, msgid, p["status"], allowed))
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
    print()
    print("=== waiting for the bridge to restart ===")
    # Air and Air 2 are back within 4 s; an Air 2 Pro takes noticeably longer.
    for _ in range(15):
        time.sleep(2.0)
        try:
            dev = Glasses()
            break
        except SystemExit:
            continue
    else:
        print("  HID did not come back after 30 s. Unplug and replug the cable.")
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
    """Check framing plus the fixed public image/profile contract."""
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
    if not ok:
        raise AssertionError("framing self-test failed")

    expected = {
        0x0424: (
            "66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA",
            "34AEE893AC697D314CB522D135AAE8C9222CC9461B62C096C616FEF44DE87AD8",
        ),
        0x0428: (
            "350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3",
            "46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486",
        ),
    }
    for pid, hashes in expected.items():
        profile = WRITE_PROFILES[pid]
        assert (profile["stock_sha"], profile["output_sha"]) == hashes
        assert PID_TO_PROJECT[pid] == profile["project"]
        assert image_approved(profile, hashes[0])
        assert image_approved(profile, hashes[1])
        assert not image_approved(profile, "0" * 64)
    pro = WRITE_PROFILES[0x0432]
    assert (pro["stock_sha"], pro["output_sha"]) == expected[0x0428]
    assert KNOWN_IMAGES[pro["stock_sha"]][0] == {0x0428, 0x0432}
    assert KNOWN_IMAGES[pro["output_sha"]][0] == {0x0428, 0x0432}
    assert plan_chunks(64) == [("START", START, 0, 42), ("START", START, 42, 64)]
    print("  -> Air/Air 2/Air 2 Pro exact SHA profiles match")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Write DP bridge firmware. Writes nothing unless --flash is given.")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--image", "-i", default=None)
    source.add_argument("--restore", action="store_true",
                        help="write back the connected model's stock image from firmware/")
    ap.add_argument("--flash", action="store_true", help="actually send it")
    ap.add_argument("--after-power-cycle", action="store_true",
                    help="records that the MCU was reset after a failed write; "
                         "not needed before a normal write")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test and (a.image or a.restore or a.flash or a.after_power_cycle):
        ap.error("--self-test cannot be combined with image, restore, or write options")
    if a.flash and not (a.image or a.restore):
        ap.error("--flash requires --image or --restore")
    if a.self_test:
        print("=== framing self-test ===")
        return self_test()

    dev = Glasses()
    print("=== connected glasses ===")
    print("  %s (VID 0x%04X / PID 0x%04X) projectCode 0x%04X"
          % (dev.name, VID, dev.pid, dev.project or 0))
    print("  DP firmware version = %r" % dev.version())
    profile = WRITE_PROFILES[dev.pid]
    path = profile["stock"] if a.restore else (Path(a.image) if a.image else None)
    if path is None:
        print("\nPass --image to inspect an image, or --restore to write stock back.")
        dev.close()
        return

    try:
        img = path.read_bytes()
    except OSError as e:
        dev.close()
        sys.exit("cannot read image %s: %s" % (path, e))
    print("\n=== inspecting: %s ===" % path)
    check_image(img, dev)

    steps = plan_chunks(len(img))
    print("\n=== chunk plan ===")
    print("  PREPARE(110) -> START(111) x2 (header) -> TRANSMIT(112) x%d -> FINISH(113)"
          % sum(1 for s in steps if s[0] == "TRANSMIT"))
    print("  %d packets total / %d B payload" % (len(steps) + 2, len(img)))

    if not a.flash:
        print("\nNo update command was sent; nothing was written. Add --flash to write it.")
        print("  The bridge restarts itself after a successful FINISH, so no replug")
        print("  is needed before or after.")
        dev.close()
        return

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
