#!/usr/bin/env python3
r"""Read and write the Sony micro-OLED panel registers, through the MCU peek.

REQUIRES THE MCU IMAGE BUILT BY THIS KIT
    The peek lives on msgid 0x5B. Stock firmware answers that message id with
    0x23 for everything, so if every register reads back as 0x23 the peek is
    not installed. --selftest checks exactly that.

WHY READ THEM
    The Air's MCU writes only ten panel registers
    (0x00 0x02 0x0B 0x10 0x15 0x3B 0x3C 0x82 0x8B 0xBF); the remaining ~180 sit
    at their power-on defaults. Reading the real values is how you tell whether
    something on the panel side, rather than the bridge side, is holding the
    display to a particular geometry.

    The dump can compare against a reference register table, if you have one:
    put it in a file named ecx34x_init_ref.json next to this script, as a JSON
    object mapping a label to a hex string of the 191 bytes written to
    registers 0x01..0xBF. No such file is distributed here. Without it the
    reference columns simply read "--" and everything else still works.

PANEL REGISTERS ARE VOLATILE
    They live in RAM, not flash. A bad write is undone by a power cycle. The
    one to be careful with is reg 0x82, which selects the register bank: put it
    back to 0 when you are done, which --dump does for you.

USAGE
  python panelreg.py --selftest            check only that the peek responds
  python panelreg.py --dump                dump 0x00..0xBF for both eyes
  python panelreg.py --dump --map 2        switch to bank 2 first, then dump
  python panelreg.py --read 0 0x0E         read one register from the right eye
  python panelreg.py --write 0 0x0E 0x44   write it (volatile)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hid
from glasses import VID, CTRL_IF, PIDS, build_fd, parse

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PEEK_MSGID = 0x5B
MAGIC_R, MAGIC_W = 0xA5, 0x5A
# Confirmed on hardware: eye=0 is the right eye and eye=1 the left.
EYES = {0: "right", 1: "left"}
REF = HERE / "ecx34x_init_ref.json"

# The ten registers the stock MCU actually writes. These are not defaults.
MCU_WRITES = {0x00, 0x02, 0x0B, 0x10, 0x15, 0x3B, 0x3C, 0x82, 0x8B, 0xBF}


def open_ctrl():
    for pid in PIDS:
        paths = {d["interface_number"]: d["path"] for d in hid.enumerate(VID, pid)}
        if CTRL_IF in paths:
            h = hid.device()
            h.open_path(paths[CTRL_IF])
            return h, pid
    sys.exit("XREAL control interface MI_04 not found.")


def xfer(h, payload: bytes, wait=1.0):
    h.write(bytes([0x00]) + build_fd(PEEK_MSGID, b"\x00" * 6 + payload, 0, 0).ljust(64, b"\x00"))
    end = time.time() + wait
    while time.time() < end:
        try:
            r = h.read(64, 150)
        except OSError:
            return None
        if not r:
            continue
        p = parse(bytes(r))
        if p and p[0] == PEEK_MSGID and p[1] == 0x00:
            body = p[2]
            if len(body) < 7:
                return None
            return (body[5], body[6])          # (status, value)
    return None


def read_reg(h, eye: int, reg: int):
    r = xfer(h, bytes([MAGIC_R, eye & 1, reg & 0xFF]))
    return None if r is None else r[1]


def write_reg(h, eye: int, reg: int, val: int):
    return xfer(h, bytes([MAGIC_W, eye & 1, reg & 0xFF, val & 0xFF]))


def load_ref():
    if not REF.exists():
        return {}
    raw = json.loads(REF.read_text())
    return {k: bytes.fromhex(v) for k, v in raw.items()}


def ref_reg(buf: bytes, reg: int):
    """The 191-byte buffer maps to registers 0x01..0xBF in order: buf[i] = reg i+1."""
    i = reg - 1
    return buf[i] if 0 <= i < len(buf) else None


def cmd_selftest(h):
    vals = [read_reg(h, 1, r) for r in (0x00, 0x0E, 0x3B, 0x8B)]
    print("  probe reg 00/0E/3B/8B =", " ".join("--" if v is None else "%02X" % v for v in vals))
    if all(v == 0x23 for v in vals):
        print("  All 0x23: that is the stock reserved-message reply. The peek is not installed.")
        return False
    if all(v is None for v in vals):
        print("  No answer.")
        return False
    if len(set(vals)) == 1:
        print("  Every register read back the same value; the peek may not be working.")
        return False
    print("  The peek is alive: registers return distinct values.")
    return True


def cmd_dump(h, lo, hi, mapno):
    ref = load_ref()
    if mapno is not None:
        for e in (0, 1):
            write_reg(h, e, 0x82, mapno)
        print("  switched reg 0x82 = %d (bank %d)\n" % (mapno, mapno))

    got = {}
    for e in (0, 1):
        for r in range(lo, hi + 1):
            got[(e, r)] = read_reg(h, e, r)

    if mapno is not None:
        for e in (0, 1):
            write_reg(h, e, 0x82, 0)
        print("  restored reg 0x82 = 0 (bank 0)\n")

    a = ref.get("setA(ECX343E)|5L2_120")
    b = ref.get("ECX348|5L2_120")
    print("  reg   L   R  | ref A   ref B  | notes")
    print("  " + "-" * 58)
    mism_a = mism_b = 0
    for r in range(lo, hi + 1):
        vl, vr = got[(1, r)], got[(0, r)]
        ra = ref_reg(a, r) if a else None
        rb = ref_reg(b, r) if b else None
        note = []
        if r in MCU_WRITES:
            note.append("written by the MCU")
        if vr is not None and ra is not None:
            if vr != ra:
                mism_a += 1
            if rb is not None and vr == rb and vr != ra:
                note.append("matches ref B")
            elif rb is not None and vr == ra and vr != rb:
                note.append("matches ref A")
        if vr is not None and rb is not None and vr != rb:
            mism_b += 1
        print("  %02X    %s  %s |   %s     %s  | %s"
              % (r,
                 "--" if vl is None else "%02X" % vl,
                 "--" if vr is None else "%02X" % vr,
                 "--" if ra is None else "%02X" % ra,
                 "--" if rb is None else "%02X" % rb,
                 " ".join(note)))
    if a:
        n = hi - lo + 1
        print("\n  right eye vs reference A: %d of %d differ" % (mism_a, n))
        print("  right eye vs reference B: %d of %d differ" % (mism_b, n))
    lr = [r for r in range(lo, hi + 1) if got[(0, r)] != got[(1, r)]]
    print("  registers that differ between the eyes: %s" % (" ".join("%02X" % r for r in lr) if lr else "none"))


def main():
    ap = argparse.ArgumentParser(description="Read and write Air panel registers.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--lo", default="0x00")
    ap.add_argument("--hi", default="0xBF")
    ap.add_argument("--map", dest="mapno", type=int, default=None,
                    help="select a register bank with reg 0x82 first, then restore it to 0")
    ap.add_argument("--read", nargs=2, metavar=("EYE", "REG"))
    ap.add_argument("--write", nargs=3, metavar=("EYE", "REG", "VAL"))
    a = ap.parse_args()

    h, pid = open_ctrl()
    print("=== connected: PID 0x%04X ===" % pid)
    try:
        if a.read:
            e, r = int(a.read[0], 0), int(a.read[1], 0)
            v = read_reg(h, e, r)
            print("  %s eye reg 0x%02X = %s" % (EYES[e & 1], r, "no answer" if v is None else "0x%02X" % v))
            return
        if a.write:
            e, r, v = (int(x, 0) for x in a.write)
            print("  %s eye reg 0x%02X <- 0x%02X  (volatile; a power cycle undoes it)" % (EYES[e & 1], r, v))
            write_reg(h, e, r, v)
            back = read_reg(h, e, r)
            print("  read back = %s" % ("no answer" if back is None else "0x%02X" % back))
            return
        if a.selftest or not a.dump:
            if not cmd_selftest(h) or not a.dump:
                return
        cmd_dump(h, int(a.lo, 0), int(a.hi, 0), a.mapno)
    finally:
        try:
            h.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
