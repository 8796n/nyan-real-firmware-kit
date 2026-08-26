#!/usr/bin/env python3
r"""Switch the XREAL Air display mode, and optionally re-dump the EDID.

Handles the Air (gen 1), the Air 2 and the Air 2 Pro. The mode numbers are the
vendor menu ids and are shared, but the menus are not: the Air 2 and Air 2 Pro
have no mode 8, and their mode 9 needs an HBR2 DP link that the p55 stock image
does not set up, so there it is refused unless --hbr2 says an image that has it
is flashed. That is a statement about the firmware, not about the model, and
nothing here can read back which image is on the glasses.

The glasses expose several logical display modes. Mode 1 is the adaptive one
the device boots into; the others pin a fixed refresh rate or select a
side-by-side 3D layout. Each mode presents a different EDID, which is why this
tool can dump the EDID again right after switching.

On the Air (gen 1) only mode 1 uses the E0BF=2 timing path; every other mode
uses E0BF=0. So switching between mode 1 and mode 10 exercises both paths
without ever leaving 2D, which keeps a picture on screen while you look at the
difference. E0BF is gen-1 DP firmware internals, so that column is shown for
the Air (gen 1) only.

SAFETY
  * The display mode is volatile. Unplugging and replugging restores the
    default, so nothing here can leave the glasses in a bad mode permanently.
  * Switching toggles HPD, so the screen drops for a few seconds. That is also
    what makes the host re-read the EDID.
  * Message 0x07 reports the current state of the DP link, not a readback of
    what you wrote. It also moves when the host changes refresh rate, so a
    matching value is not by itself proof that the switch took effect.
  * The gaps in the numbering (2, 6, 7, plus 8 on the Air 2 and Air 2 Pro) are
    not sent. Brute-forcing display mode values on a related device produced
    black screens and dropped DP links.
  * Only the APP PIDs are opened. In BOOT (0x0423 / 0x0427 / 0x0431) the MCU
    sits in its bootloader and has no display mode to switch.
  * Nothing is written to flash. The only thing touched is the volatile mode
    register.

USAGE
  python display.py                show the current mode only (read-only)
  python display.py 10             switch to the 90 Hz 2D mode
  python display.py 1              back to mode 1, the adaptive default
  python display.py --list         list the values the connected model takes
  python display.py --probe 10     switch, re-dump the EDID, then switch back
  python display.py 9 --hbr2       mode 9 on an Air 2 family image that has HBR2
"""
import os
import subprocess
import sys
import time
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hid
from glasses import build_fd, parse, detect_pid, VID, CTRL_IF

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

# Values and names are the vendor menu ids, shared across the Air family.
# The second field is the E0BF timing path each mode selects on the Air (gen 1);
# E0BF belongs to the gen-1 DP image, so it is not reported for the Air 2 family.
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

# What --hbr2 asserts is a property of the flashed image, not of the model: the
# Air 2 and Air 2 Pro run the same p55 stock image, and stock has no HBR2 link
# for mode 9. dp_flash.py will not put this kit's Air 2 output on a Pro (that
# patch edits the "Air 2" EDID base block and would be inert there), so on a Pro
# the flag means an image you built yourself. Either way the tool cannot read
# back which image is flashed, so it asks rather than guesses.
HBR2_MODE9 = {9: ("needs an HBR2 DP link; on stock firmware it comes up black.\n"
                  "This kit's Air 2 DP image adds one -- on an Air 2 Pro, where\n"
                  "dp_flash.py will not write that image, --hbr2 means an image you\n"
                  "built. Flash one, then pass --hbr2.", "--hbr2")}

# APP PIDs only. The matching BOOT PIDs (0x0423 / 0x0427 / 0x0431) are never
# opened: there the MCU is in its bootloader and has no display mode.
# menu    = the values the vendor offers on that model; nothing else is sent.
# blocked = values in the menu that are refused unless their flag is given.
MODELS = {
    0x0424: dict(name="Air (gen 1)", e0bf=True,
                 menu=(1, 5, 10, 11, 3, 4, 8, 9), blocked={}),
    0x0428: dict(name="Air 2", e0bf=False,
                 menu=(1, 5, 10, 11, 3, 4, 9), blocked=HBR2_MODE9),
    0x0432: dict(name="Air 2 Pro", e0bf=False,
                 menu=(1, 5, 10, 11, 3, 4, 9), blocked=HBR2_MODE9),
}

# Modes that reach the E0BF==0 path while staying in 2D. Every model has them.
SAFE_2D = (1, 5, 10, 11)
MSG_R, MSG_W = 0x07, 0x08

HERE = os.path.dirname(os.path.abspath(__file__))
EDID_TOOL = os.path.join(HERE, "edid_dump.py")


def open_ctrl():
    """Open MI_04 on a supported APP device. Returns (handle, pid)."""
    seen = {}
    for d in hid.enumerate(VID, 0):
        if d.get("interface_number") == CTRL_IF:
            seen.setdefault(int(d["product_id"]), d["path"])
    supported = [pid for pid in MODELS if pid in seen]
    if len(supported) > 1:
        sys.exit("multiple XREAL control devices found (%s). Connect exactly one pair."
                 % ", ".join("0x%04X" % p for p in supported))
    if supported:
        h = hid.device()
        h.open_path(seen[supported[0]])
        return h, supported[0]
    if seen:
        sys.exit("connected XREAL device (PID %s) has no display mode this tool can "
                 "switch.\nSupported: %s."
                 % (", ".join("0x%04X" % p for p in sorted(seen)),
                    ", ".join("%s 0x%04X" % (m["name"], p) for p, m in MODELS.items())))
    sys.exit("XREAL control interface MI_04 not found (VID 3318 / PID %s).\n"
             "Plug the glasses directly into this PC."
             % " / ".join("%04X" % p for p in MODELS))


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


def refuse(model, want, argv):
    """Why `want` must not be sent to this model, or None if it may be sent."""
    if want not in model["menu"]:
        return ("Value %d is not in the %s menu. Only %s can be sent."
                % (want, model["name"], sorted(model["menu"])))
    why, flag = model["blocked"].get(want, (None, None))
    if why and flag not in argv:
        return "mode %d is refused on the %s: %s" % (want, model["name"], why)
    return None


def show(h, label, model):
    st, val = xfer(h, MSG_R)
    if st is None:
        print("   %s: no answer" % label)
        return None
    name, bf = MODES.get(val, ("unknown value", None))
    if val not in model["menu"]:
        name += ", not in this model's menu"
    print("   %s: 0x07 -> status=%02x  value=%s (%s)%s"
          % (label, st, val, name,
             "   E0BF=%d" % bf if model["e0bf"] and bf is not None else ""))
    return val


def switch(h, want, model):
    print("\n=== writing %d (%s) to 0x08 ===" % (want, MODES[want][0]))
    print("The screen will drop for a few seconds as HPD toggles. If anything goes")
    print("wrong, unplug and replug the cable.")
    st, _ = xfer(h, MSG_W, struct.pack("<I", want))
    print("   0x08 status=%s   (a fixed ack; not proof the switch took effect)"
          % ("%02x" % st if st is not None else "no answer"))
    for i in range(6):
        time.sleep(1.0)
        try:
            got = show(h, "check %d" % (i + 1), model)
        except OSError:
            print("   check %d: read error, reopening" % (i + 1))
            try:
                h.close()
            except Exception:
                pass
            time.sleep(0.5)
            h, _ = open_ctrl()
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


def self_test():
    """Check the model table offline: no BOOT PID, no value outside the menu."""
    from glasses import PIDS
    for pid, m in MODELS.items():
        assert "(APP)" in PIDS[pid], "0x%04X is not an APP PID" % pid
        assert set(m["menu"]) <= set(MODES), m["name"]
        assert set(m["blocked"]) <= set(m["menu"]), m["name"]
        assert set(SAFE_2D) <= set(m["menu"]), m["name"]
        print("  %-12s menu %s  refused %s"
              % (m["name"], sorted(m["menu"]), sorted(m["blocked"]) or "none"))
    for pid in (0x0423, 0x0427, 0x0431):
        assert pid not in MODELS, "BOOT PID 0x%04X must never be opened" % pid
    for pid in (0x0428, 0x0432):                    # Air 2 family
        assert 8 not in MODELS[pid]["menu"]         # not in the vendor menu
        assert 9 in MODELS[pid]["blocked"]          # needs HBR2
    assert 8 in MODELS[0x0424]["menu"] and not MODELS[0x0424]["blocked"]

    # The gate itself. --hbr2 is a claim about the flashed image, so it reads the
    # same on both Air 2 family members; nothing else opens mode 9.
    air, air2, pro = (MODELS[p] for p in (0x0424, 0x0428, 0x0432))
    assert refuse(air, 8, []) is None and refuse(air, 9, []) is None
    assert refuse(air2, 8, []) and refuse(pro, 8, ["--hbr2"])       # 8 not in the menu
    for m in (air2, pro):
        assert refuse(m, 9, [])                                    # stock: black
        assert refuse(m, 9, ["--probe"])                            # only --hbr2 opens it
        assert refuse(m, 9, ["--hbr2"]) is None                     # image with HBR2
    assert refuse(pro, 10, []) is None and refuse(pro, 2, [])
    print("  -> APP PIDs only; BOOT never listed; Air 2 family has no 8 and refuses 9")
    print("  -> mode 9 opens on the Air 2 family with --hbr2 only")


def main():
    argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    if "--list" in argv:
        pid = detect_pid()
        model = MODELS.get(pid, MODELS[0x0424])
        print("%s (PID 0x%04X)" % (model["name"], pid))
        print("value  %smode" % ("E0BF  " if model["e0bf"] else ""))
        for k in sorted(model["menu"]):
            note = (("   (stays in 2D)" if k in SAFE_2D else "")
                    + ("   REFUSED" if k in model["blocked"] else ""))
            if model["e0bf"]:
                print("  %2d     %d    %s%s" % (k, MODES[k][1], MODES[k][0], note))
            else:
                print("  %2d   %s%s" % (k, MODES[k][0], note))
        print("\nValues outside that list are not in the menu and are never sent.")
        if model["e0bf"]:
            print("Only mode 1 uses E0BF=2; every other mode uses E0BF=0.")
        for k, (why, flag) in model["blocked"].items():
            print("\nmode %d: %s%s" % (k, why, "\nOverride with %s." % flag if flag else ""))
        return

    probe = "--probe" in argv
    args = [a for a in argv if not a.startswith("-")]

    h, pid = open_ctrl()
    model = MODELS[pid]
    try:
        print("\n=== current display mode (%s) ===" % model["name"])
        cur = show(h, "current", model)
        if not args:
            print("\nPass a value to switch, e.g. python display.py 10")
            print("--list shows the values; --probe 10 switches, dumps and restores")
            return

        want = int(args[0], 0)
        no = refuse(model, want, argv)
        if no:
            sys.exit("\n%s\nNothing was sent." % no)
        if want in model["blocked"]:
            print("\n%s given: sending mode %d anyway. If the screen stays black,"
                  % (model["blocked"][want][1], want))
            print("unplug and replug -- the mode is volatile.")
        if probe and want not in SAFE_2D:
            sys.exit("\n--probe is limited to the 2D modes %s.\n"
                     "To measure a 3D mode, switch to it and check by hand." % (SAFE_2D,))

        if want == cur:
            print("\nAlready in %s." % MODES[want][0])
        else:
            h, ok = switch(h, want, model)
            if probe and not ok:
                print("\nThe switch could not be confirmed, so the EDID dump is skipped.")
                return

        if probe:
            dump_edid("mode%d" % want)
            # 0x07 reports the DP link, so `cur` can be a value this model never
            # takes. Only send it back if it is one we are allowed to send.
            if cur is not None and cur != want and cur in model["menu"] \
                    and cur not in model["blocked"]:
                print("\n=== switching back to mode %d ===" % cur)
                h, _ = switch(h, cur, model)
                dump_edid("mode%d_restored" % cur)
            elif cur is not None and cur != want:
                print("\nNot switching back: %s is not a value this tool sends on the %s."
                      % (cur, model["name"]))
            print("\ncompare: python edid_dump.py --diff mode%d mode%d" % (cur or 1, want))
    finally:
        try:
            h.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
