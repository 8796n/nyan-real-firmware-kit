#!/usr/bin/env python3
"""Measure the panel VSYNC rate reported by the glasses (IF#5, endpoint 0x88).

The MCU raises an interrupt on the panel's PD1 rising edge -- that is the OLED
VSYNC -- and pushes ``{sequence:u64, timestamp_ns:u64}`` to this endpoint. The
rate normally matches the display mode's real refresh rate.

It does not always match the mode id, though: driving 720p60 into the scaler
while the glasses sit in a 120 Hz mode measures 60.0 Hz. So do not conclude
from a mode id alone that frame doubling is running. This tool prints both the
USB arrival rate and the period computed from the glasses' own timestamps.

Note that the timestamp is taken inside the interrupt handler, so heavy MCU
load -- USB audio playback, for instance -- shows up as jitter here even when
the panel itself is on time. A frame count that stays exact is the sign that
the panel is fine and only the timestamping slipped.

Read-only. This tool never writes to the glasses.

Usage:
  python vsync.py [seconds]        default 6
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hid
from glasses import VID, PID, AUX_IF

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0

paths = {d["interface_number"]: d["path"] for d in hid.enumerate(VID, PID)}
if AUX_IF not in paths:
    sys.exit("IF#5 not found. Plug the glasses into this PC directly. (interfaces seen: %s)"
             % sorted(paths))

h = hid.device()
h.open_path(paths[AUX_IF])
print("Listening on IF#5 (endpoint 0x88) for %.1f s ... nothing is written" % seconds,
      flush=True)

count, first, last, samples, timestamps = 0, None, None, [], []
end = time.time() + seconds
try:
    while time.time() < end:
        try:
            report = h.read(64, 200)
        except OSError as exc:
            print("read error: %s" % exc)
            break
        if not report:
            continue
        now = time.time()
        if first is None:
            first = now
        last = now
        count += 1
        if len(report) >= 16:
            # hidapi strips the IF#5 report header, so the payload starts at 0.
            timestamps.append(int.from_bytes(bytes(report[8:16]), "little"))
        if len(samples) < 3:
            samples.append(bytes(report).hex())
finally:
    try:
        h.close()
    except Exception:
        pass

print()
if count < 2 or first is None or last is None or last <= first:
    print("No frames arrived (n=%d). The display may be off, or the mode may have "
          "just changed." % count)
else:
    span = last - first
    print("  USB arrivals   : %d in %.2f s = **%.1f Hz**" % (count, span, count / span))
    deltas = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if deltas:
        period = statistics.median(deltas)
        print("  panel timestamp: median %.0f ns = **%.3f Hz**" % (period, 1e9 / period))
        if len(deltas) >= 2:
            jitter = [d - period for d in deltas]
            print("                   min/max %.0f / %.0f ns, p-p %.0f ns, stdev %.0f ns"
                  % (min(deltas), max(deltas), max(deltas) - min(deltas),
                     statistics.pstdev(jitter)))
for i, sample in enumerate(samples):
    print("  sample%d: %s" % (i + 1, sample[:64]))
