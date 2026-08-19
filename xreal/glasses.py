#!/usr/bin/env python3
"""Shared USB HID plumbing for XREAL glasses: device identification and framing.

All the tools in this directory talk to the glasses through the same control
interface and the same frame format, so both live here.

Frame format (report 0, 64 bytes, zero padded):

    fd | crc32-LE(4) | len-u16-LE | seq(4) | ts(4) | msgid(1) | payload

``len`` counts everything from ``seq`` onwards plus 2. Responses come back in
the same shape; :func:`parse` returns ``(msgid, namespace, body)``.

Reading is safe. Nothing here writes to the glasses -- the tools that do say so
themselves.
"""
import os
import struct
import zlib

import hid

VID = 0x3318

# This table identifies what is plugged in. It is not a list of supported
# devices: the tools here are written for and verified on the Air (gen 1).
# The XREAL One family speaks a different protocol entirely and is not listed.
#
# The MCU reports APP or BOOT depending on its own state. That says nothing
# about the DP bridge: seeing BOOT only means the MCU sits in its bootloader,
# for instance after a MCU_App_Jump_to_Boot request.
PIDS = {
    0x0432: "Air 2 Pro (APP)",   0x0431: "Air 2 Pro (BOOT)",
    0x0428: "Air 2 (APP)",       0x0427: "Air 2 (BOOT)",
    0x0424: "Air (APP)",         0x0423: "Air (BOOT)",
    0x0441: "xbx a01+ (APP)",    0x0442: "xbx a01+ (BOOT)",
}

_PID_DEFAULT = 0x0424            # assumed when nothing is connected

# USB interface numbers. MI_04 is the control interface (EP 0x07 / 0x86).
CTRL_IF, IMU_IF, AUX_IF = 4, 3, 5


def detect_pid(default=_PID_DEFAULT):
    """Return the PID of the connected glasses, preferring APP over BOOT.

    Override with the XREAL_PID environment variable when autodetection picks
    the wrong device.
    """
    env = os.environ.get("XREAL_PID")
    if env:
        return int(env, 0)
    try:
        seen = {d["product_id"] for d in hid.enumerate(VID, 0)}
    except Exception:
        return default
    for pid in (0x0432, 0x0428, 0x0424, 0x0441):      # APP entries first
        if pid in seen:
            return pid
    for pid in seen:
        if pid in PIDS:
            return pid
    return default


PID = detect_pid()
PID_NAME = PIDS.get(PID, "unknown 0x%04X" % PID)


def build_fd(msgid, payload=b"", seq=0, ts=0):
    """Build one control frame.

    Never call this with an empty payload. A 16-byte frame (len 0x000b) crashes
    the xbx a01+ MCU and has never been tested on the Air, so every legitimate
    frame carries at least the six pad bytes the callers prepend.
    """
    body = struct.pack("<IIB", seq, ts, msgid) + payload
    tail = struct.pack("<H", len(body) + 2) + body
    return b"\xfd" + struct.pack("<I", zlib.crc32(tail) & 0xFFFFFFFF) + tail


def parse(b):
    """Split a response frame into (msgid, namespace, body), or None."""
    if b and b[0] == 0xFD and len(b) >= 16:
        length = int.from_bytes(b[5:7], "little")
        return b[15], b[16], bytes(b[17:5 + length])
    return None
