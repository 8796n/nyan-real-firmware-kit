#!/usr/bin/env python3
r"""Read DP bridge (LT7911 / DP7911) registers from the host. Read-only.

REQUIRES THE MCU IMAGE BUILT BY THIS KIT
    Stock firmware exposes no message id that lets the host name an arbitrary
    register address. The MCU build in this repository adds a generic peek on
    msgid 0x29, and that is what this tool uses. Against stock firmware every
    read simply times out.

    Writing is deliberately not implemented. The vendor's own tool refuses to
    write anything except one register, and this tool writes nothing at all.

WHY IT IS USEFUL
    Registers 0xE7C3..0xE7D1 hold the timing window the DP firmware is driving
    onto the LVDS side. Reading them tells you what the bridge is actually
    emitting, which is how you separate a bridge-side problem from a panel-side
    one -- for instance when the bottom of the image is cut off, or when you
    want to confirm that a 1200-line build really reached the panel link.

USAGE
  python dpreg.py                    read the default set: link state + LVDS window
  python dpreg.py E7C9 E7CA          read specific addresses
  python dpreg.py --sweep E7C0 E7D8  sweep a range
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hid
from glasses import VID, CTRL_IF, PIDS, build_fd, parse

R_LT7911_REG = 237          # One / a01+ family; not implemented on the Air

# The generic peek this kit's MCU build installs on msgid 0x29.
#   request  buf[0]=0xA5 / buf[1]=page / buf[2]=reg
#   response buf[0]=value, out_len=1
PEEK_MSGID = 0x29
PEEK_MAGIC = 0xA5

# (address, name, what to expect)
DEFAULT = [
    (0xE0B7, "model id (static EDID select)", "not 1..4 on the Air"),
    (0xE0B8, "lane count", "4"),
    (0xE0B9, "link rate", "0x0A=HBR / 0x06=RBR / 0x14=HBR2"),
    (0xE0BA, "source of [06E8]", "0 or 1"),
    (0xE0BF, "timing struct select", "2 in mode 1"),
    (0xE086, "DP->MCU resolution class", "0 = 1080 lines, 2 = 1200 lines"),
    (0xE087, "DP->MCU refresh class", "0=60 1=72 2=90 3=120"),
    (0xE7C3, "(hsw+hbp)/2 hi", "96 = 0x0060"),
    (0xE7C4, "(hsw+hbp)/2 lo", ""),
    (0xE7C5, "vsw+vbp hi", "41 = 0x0029"),
    (0xE7C6, "vsw+vbp lo", ""),
    (0xE7C7, "Hactive/2 hi", "960 = 0x03C0"),
    (0xE7C8, "Hactive/2 lo", ""),
    (0xE7C9, "Vactive hi", "1200 = 0x04B0; stock is 1080 = 0x0438"),
    (0xE7CA, "Vactive lo", ""),
    (0xE7CB, "Htotal/2 hi", "1100 = 0x044C"),
    (0xE7CC, "Htotal/2 lo", ""),
    (0xE7CD, "Vtotal hi", "1250 = 0x04E2; stock is 1125 = 0x0465"),
    (0xE7CE, "Vtotal lo", ""),
    (0xE7CF, "hsw/2 hi", "22 = 0x0016"),
    (0xE7D0, "hsw/2 lo", ""),
    (0xE7D1, "vsw low 8 bits", "5"),
]

PAIRS = {0xE7C3: "hsw+hbp /2", 0xE7C5: "vsw+vbp", 0xE7C7: "Hactive /2",
         0xE7C9: "Vactive", 0xE7CB: "Htotal /2", 0xE7CD: "Vtotal", 0xE7CF: "hsw /2"}


def open_ctrl():
    for pid in PIDS:
        paths = {d["interface_number"]: d["path"] for d in hid.enumerate(VID, pid)}
        if CTRL_IF in paths:
            h = hid.device()
            h.open_path(paths[CTRL_IF])
            return h, pid
    sys.exit("XREAL control interface MI_04 not found.")


def read_reg(h, addr, wait=1.2, msgid=None):
    """Read one byte from a DP bridge register, or None if it does not answer.

    The address is 16-bit: the high half is the page and the low half the
    register, which mirrors how the stock firmware reads them internally.
    """
    msgid = PEEK_MSGID if msgid is None else msgid
    if msgid == PEEK_MSGID:
        payload = bytes([PEEK_MAGIC, (addr >> 8) & 0xFF, addr & 0xFF])
    else:                                     # R_LT7911_REG on One / a01+
        payload = bytes([addr & 0xFF, (addr >> 8) & 0xFF])
    h.write(bytes([0x00]) + build_fd(msgid, b"\x00" * 6 + payload, 0, 0).ljust(64, b"\x00"))
    end = time.time() + wait
    while time.time() < end:
        try:
            r = h.read(64, 150)
        except OSError:
            return None
        if not r:
            continue
        p = parse(bytes(r))
        if p and p[0] == (msgid & 0xFF) and p[1] == 0x00:
            body = p[2]                       # after the 5 pad bytes: status + data
            if len(body) < 7:
                return None
            return (body[5], body[6])         # (status, value)
    return None


def main():
    argv = sys.argv[1:]
    h, pid = open_ctrl()
    print("=== connected: PID 0x%04X ===" % pid)
    try:
        if "--sweep" in argv:
            i = argv.index("--sweep")
            a0, a1 = int(argv[i + 1], 16), int(argv[i + 2], 16)
            for a in range(a0, a1 + 1):
                r = read_reg(h, a)
                print("  %04X = %s" % (a, "no answer" if r is None
                                       else ("status=%02X val=0x%02X" % r)))
            return

        targets = ([(int(x, 16), "", "") for x in argv] if argv else DEFAULT)
        vals = {}
        print("  %-6s %-26s %-12s %s" % ("addr", "meaning", "value", "expected"))
        for addr, name, exp in targets:
            r = read_reg(h, addr)
            if r is None:
                print("  %04X   %-26s %-12s %s" % (addr, name, "no answer", exp))
                continue
            status, val = r
            vals[addr] = val
            print("  %04X   %-26s status=%02X 0x%02X  %s" % (addr, name, status, val, exp))

        # Reassemble the 16-bit pairs and label them
        got = [a for a in PAIRS if a in vals and (a + 1) in vals]
        if got:
            print("\n  --- LVDS window (16-bit) ---")
            for a in sorted(got):
                v = (vals[a] << 8) | vals[a + 1]
                print("    %04X:%04X  %-12s = %d" % (a, a + 1, PAIRS[a], v))
            if 0xE7C9 in vals and 0xE7CA in vals:
                va = (vals[0xE7C9] << 8) | vals[0xE7CA]
                vt = (vals[0xE7CD] << 8) | vals[0xE7CE] if 0xE7CD in vals else None
                print("\n    Vactive = %d %s" % (va, "-- 1200 lines reached the panel link"
                                                 if va == 1200 else
                                                 "-- still 1080; the bridge is not driving 1200" if va == 1080
                                                 else "-- unexpected"))
                if vt:
                    print("    Vtotal  = %d" % vt)
    finally:
        try:
            h.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
