#!/usr/bin/env python3
r"""Switch the XREAL Air (gen 1) display mode, and optionally re-dump the EDID.

The glasses expose several logical display modes. Mode 1 is the adaptive one
the device boots into; the others pin a fixed refresh rate or select a
side-by-side 3D layout. Each mode presents a different EDID, which is why this
tool can dump the EDID again right after switching.

Only mode 1 uses the E0BF=2 timing path; every other mode uses E0BF=0. So
switching between mode 1 and mode 10 exercises both paths without ever leaving
2D, which keeps a picture on screen while you look at the difference.

SAFETY
  * The display mode is volatile. Unplugging and replugging restores the
    default, so nothing here can leave the glasses in a bad mode permanently.
  * Switching toggles HPD, so the screen drops for a few seconds. That is also
    what makes the host re-read the EDID.
  * Message 0x07 reports the current state of the DP link, not a readback of
    what you wrote. It also moves when the host changes refresh rate, so a
    matching value is not by itself proof that the switch took effect.
  * The gaps in the numbering (2, 6, 7) are not sent. Brute-forcing display
    mode values on a related device produced black screens and dropped DP
    links.
  * Nothing is written to flash. The only thing touched is the volatile mode
    register.

USAGE
  python display.py                show the current mode only (read-only)
  python display.py 10             switch to the 90 Hz 2D mode
  python display.py 1              back to mode 1, the adaptive default
  python display.py --list         list the values
  python display.py --probe 10     switch, re-dump the EDID, then switch back
"""
import os
import subprocess
import sys
import time
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hid
from glasses import build_fd, parse, VID, CTRL_IF

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

AIR_PIDS = (0x0424,)          # Air (APP) only; never touch modes in BOOT (0x0423)

# Values and names are the vendor menu ids, shared with the Air 2.
# The second field is the E0BF timing path each mode selects.
# Note these are the stock labels: with this kit's firmware the 2D modes also
# carry 1920x1200 timings.
MODES = {
    1:  ("2D 60Hz (adaptive default)", 2),
    5:  ("2D 72Hz",                    0),
    10: ("2D 90Hz",                    0),
    11: ("2D 120Hz",                   0),
    3:  ("3D side-by-side 60Hz",       0),
    4:  ("3D side-by-side 72Hz",       0),
    8:  ("3D half-SBS 60Hz (scaler)",  0),
    9:  ("3D side-by-side 90Hz",       0),
}
# Modes that reach the E0BF==0 path while staying in 2D.
SAFE_2D = (1, 5, 10, 11)
MSG_R, MSG_W = 0x07, 0x08

HERE = os.path.dirname(os.path.abspath(__file__))
EDID_TOOL = os.path.join(HERE, "edid_dump.py")


def open_ctrl():
    for pid in AIR_PIDS:
        paths = {d["interface_number"]: d["path"] for d in hid.enumerate(VID, pid)}
        if CTRL_IF in paths:
            h = hid.device()
            h.open_path(paths[CTRL_IF])
            return h
    sys.exit("XREAL Air control interface MI_04 not found (VID 3318 / PID 0424).\n"
             "Plug the glasses directly into this PC.")


def xfer(h, msgid, payload=b"", wait=0.8):
    """Send one frame and wait for the same msgid. Reply = 5 pad + status + data."""
    frame = build_fd(msgid, b"\x00" * 6 + payload, 0x9100, 0)
    h.write(bytes([0x00]) + frame.ljust(64, b"\x00"))
    end = time.time() + wait
    while time.time() < end:
        try:
            r = h.read(64, 150)
        except OSError:
            break
        if not r:
            continue
        p = parse(bytes(r))
        if p and p[1] == 0x00 and p[0] == msgid:
            body = p[2]
            status = body[5] if len(body) > 5 else None
            val = int.from_bytes(body[6:10], "little") if len(body) >= 10 else None
            return status, val
    return None, None


def show(h, label):
    st, val = xfer(h, MSG_R)
    if st is None:
        print("   %s: no answer" % label)
        return None
    name, bf = MODES.get(val, ("unknown value", None))
    print("   %s: 0x07 -> status=%02x  value=%s (%s)%s"
          % (label, st, val, name, "   E0BF=%d" % bf if bf is not None else ""))
    return val


def switch(h, want):
    print("\n=== writing %d (%s) to 0x08 ===" % (want, MODES[want][0]))
    print("The screen will drop for a few seconds as HPD toggles. If anything goes")
    print("wrong, unplug and replug the cable.")
    st, _ = xfer(h, MSG_W, struct.pack("<I", want))
    print("   0x08 status=%s   (a fixed ack; not proof the switch took effect)"
          % ("%02x" % st if st is not None else "no answer"))
    for i in range(6):
        time.sleep(1.0)
        try:
            got = show(h, "check %d" % (i + 1))
        except OSError:
            print("   check %d: read error, reopening" % (i + 1))
            try:
                h.close()
            except Exception:
                pass
            time.sleep(0.5)
            h = open_ctrl()
            continue
        if got == want:
            print("Now in %s." % MODES[want][0])
            return h, True
    print("The readback never matched. Check what the glasses are actually showing.")
    return h, False


def dump_edid(tag):
    """Wait for Windows to refresh its cached EDID after the HPD toggle, then dump."""
    print("\n=== re-dumping EDID (tag=%s) ===" % tag)
    print("  waiting for the host to pick up the new EDID ...")
    time.sleep(4.0)
    subprocess.run([sys.executable, EDID_TOOL, "--save", tag])


def main():
    argv = sys.argv[1:]
    if "--list" in argv:
        print("value  E0BF  mode")
        for k in sorted(MODES):
            print("  %2d     %d    %s%s" % (k, MODES[k][1], MODES[k][0],
                                            "   (stays in 2D)" if k in SAFE_2D else ""))
        print("\nValues 2, 6 and 7 are not in the menu and are never sent.")
        print("Only mode 1 uses E0BF=2; every other mode uses E0BF=0.")
        return

    probe = "--probe" in argv
    args = [a for a in argv if not a.startswith("-")]

    h = open_ctrl()
    try:
        print("\n=== current display mode ===")
        cur = show(h, "current")
        if not args:
            print("\nPass a value to switch, e.g. python display.py 10")
            print("--list shows the values; --probe 10 switches, dumps and restores")
            return

        want = int(args[0], 0)
        if want not in MODES:
            sys.exit("\nValue %d is not in the menu. Only %s can be sent."
                     % (want, sorted(MODES)))
        if probe and want not in SAFE_2D:
            sys.exit("\n--probe is limited to the 2D modes %s.\n"
                     "To measure a 3D mode, switch to it and check by hand." % (SAFE_2D,))

        if want == cur:
            print("\nAlready in %s." % MODES[want][0])
        else:
            h, ok = switch(h, want)
            if probe and not ok:
                print("\nThe switch could not be confirmed, so the EDID dump is skipped.")
                return

        if probe:
            dump_edid("mode%d" % want)
            if cur is not None and cur != want:
                print("\n=== switching back to mode %d ===" % cur)
                h, _ = switch(h, cur)
                dump_edid("mode%d_restored" % cur)
            print("\ncompare: python edid_dump.py --diff mode%d mode%d" % (cur or 1, want))
    finally:
        try:
            h.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
