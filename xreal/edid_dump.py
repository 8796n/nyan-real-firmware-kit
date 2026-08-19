#!/usr/bin/env python3
r"""Decode the EDID the host received from XREAL glasses. Read-only, Windows.

The DP firmware does not serve the EDID template stored in ROM verbatim: it
assembles the detailed timings at runtime and serves that. Reading what the
host actually received is therefore the only way to see what the glasses are
really advertising, and this tool never touches the glasses to do it -- it
reads the EDID Windows already cached.

WHAT IT TELLS YOU
    Which timing path produced the EDID. Mode 1 emits three detailed timings
    and overwrites the range-limits descriptor; every other mode emits two
    identical ones and keeps range limits. The decoder reports which shape it
    found and checks the fields that should hold in that case.

    Whether the first timing is 1080 or 1200 lines, which is the quickest way
    to confirm a build reached the glasses.

    Whether the timings came from the runtime builder or straight from the ROM
    template: bytes 12-14 of a detailed timing hold the physical size in mm in
    the static block, but the runtime builder puts the active pixel counts
    there instead.

CAVEAT
    What Windows holds is a cache taken at enumeration time. After changing
    display mode, unplug and replug so the host re-reads it. An entry that
    appears under WmiMonitorID is the one currently connected; the rest are
    leftovers from previous devices.

USAGE
  python edid_dump.py                    decode the current EDID and check it
  python edid_dump.py --save mode1       also save a snapshot under that tag
  python edid_dump.py --diff mode1 mode3 compare two saved snapshots
  python edid_dump.py --all              include non-XREAL displays
"""
import os
import struct
import subprocess
import sys

SCRATCH = os.path.join(os.environ.get("TEMP", "."), "air_edid")
os.makedirs(SCRATCH, exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Optional: point this at a stock DP container to diff the served EDID against
# the static template inside it. Nothing is shipped here, so this is skipped
# unless you put a file at that path yourself.
ROM = os.path.join(REPO, "firmware", "1140")
ROM_STATIC_AIR = 0x1D5C          # offset of the Air static EDID block

PS = r'''
$out = @()
Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\DISPLAY" -ErrorAction SilentlyContinue | ForEach-Object {
  $vendor = $_.PSChildName
  Get-ChildItem $_.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
    $inst = $_.PSChildName
    $dp = Join-Path $_.PSPath "Device Parameters"
    if (Test-Path $dp) {
      $e = (Get-ItemProperty $dp -Name EDID -ErrorAction SilentlyContinue).EDID
      if ($e) { $out += "$vendor|$inst|" + [System.BitConverter]::ToString($e).Replace("-","") }
    }
  }
}
$out -join "`n"
'''

PS_ACTIVE = r'''
Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue |
  ForEach-Object { $_.InstanceName }
'''


def _ps(script):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True)
    return r.stdout


def get_edids():
    res = []
    for line in _ps(PS).strip().splitlines():
        if line.count("|") == 2:
            v, i, h = line.split("|")
            try:
                res.append((v, i, bytes.fromhex(h)))
            except ValueError:
                pass
    return res


def active_instances():
    return {ln.strip().upper() for ln in _ps(PS_ACTIVE).strip().splitlines() if ln.strip()}


def mfg(b):
    """The three-letter manufacturer id packed into EDID bytes 8-9, plus the raw bytes."""
    v = (b[8] << 8) | b[9]
    return "".join(chr(((v >> sh) & 0x1F) + 64) for sh in (10, 5, 0)), b[8:12]


def dtd(b, off):
    """Expand an 18-byte detailed timing, blanking breakdown included."""
    pclk = struct.unpack_from("<H", b, off)[0] * 10           # kHz
    if pclk == 0:
        return None
    ha = b[off + 2] | ((b[off + 4] & 0xF0) << 4)
    hb = b[off + 3] | ((b[off + 4] & 0x0F) << 8)
    va = b[off + 5] | ((b[off + 7] & 0xF0) << 4)
    vb = b[off + 6] | ((b[off + 7] & 0x0F) << 8)
    hfp = b[off + 8] | ((b[off + 11] & 0xC0) << 2)
    hsw = b[off + 9] | ((b[off + 11] & 0x30) << 4)
    vfp = (b[off + 10] >> 4) | ((b[off + 11] & 0x0C) << 2)
    vsw = (b[off + 10] & 0x0F) | ((b[off + 11] & 0x03) << 4)
    ht, vt = ha + hb, va + vb
    return dict(pclk=pclk, ha=ha, va=va, ht=ht, vt=vt, hfp=hfp, hsw=hsw, hbp=hb - hfp - hsw,
                vfp=vfp, vsw=vsw, vbp=vb - vfp - vsw,
                hz=pclk * 1000.0 / (ht * vt) if ht and vt else 0.0,
                idx12=(b[off + 12] | ((b[off + 14] & 0xF0) << 4),
                       b[off + 13] | ((b[off + 14] & 0x0F) << 8)))


DESC_TAG = {0xFF: "Serial", 0xFE: "Text", 0xFC: "MonitorName",
            0xFD: "RangeLimits", 0xF7: "EstTimings3"}


def descriptors(b):
    """Return (offset, kind, detail) for all four descriptor slots."""
    out = []
    for off in (54, 72, 90, 108):
        blk = b[off:off + 18]
        if len(blk) < 18:
            continue
        if blk[0] or blk[1]:
            out.append((off, "DTD", dtd(b, off), blk))
        else:
            out.append((off, DESC_TAG.get(blk[3], "tag%02X" % blk[3]), None, blk))
    return out


def show(vendor, inst, b, active):
    print("=" * 78)
    print("  %s / %s   %d bytes %s" % (vendor, inst, len(b), "[connected]" if active else "[stale registry entry]"))
    print("=" * 78)
    if b[:8] != bytes([0, 255, 255, 255, 255, 255, 255, 0]):
        print("  bad EDID magic")
        return None
    m, raw = mfg(b)
    print("  manufacturer : %s  (raw %s)" % (m, raw[:2].hex()))
    print("  product code : 0x%04X   serial %s" % (struct.unpack_from("<H", b, 10)[0], b[12:16].hex()))
    print("  made week/yr : %d / %d      EDID version %d.%d" % (b[16], 1990 + b[17], b[18], b[19]))
    print("  screen size  : %d x %d cm" % (b[21], b[22]))
    print("  Established : %s      Standard: %s" % (b[35:38].hex(), b[38:54].hex()))
    print("  extension blocks (byte126): %d      base checksum: %s"
          % (b[126], "OK" if sum(b[:128]) % 256 == 0 else "NG"))
    print("  --- descriptors ---")
    ndtd = 0
    for off, kind, d, blk in descriptors(b):
        if kind == "DTD":
            ndtd += 1
            print("    b%-3d DTD  %s" % (off, blk.hex()))
            print("           %dx%d @%.4f Hz  pclk %d kHz" % (d["ha"], d["va"], d["hz"], d["pclk"]))
            print("           H %d + fp%d/sw%d/bp%d = ht %d    V %d + fp%d/sw%d/bp%d = vt %d"
                  % (d["ha"], d["hfp"], d["hsw"], d["hbp"], d["ht"],
                     d["va"], d["vfp"], d["vsw"], d["vbp"], d["vt"]))
            print("           index12-14 = %dx%d  %s" % (
                d["idx12"][0], d["idx12"][1],
                "<- active pixel counts: built at runtime"
                if d["idx12"] == (d["ha"], d["va"]) else "<- physical size in mm: straight from the ROM template"))
        elif kind in ("MonitorName", "Text", "Serial"):
            print("    b%-3d %-12s %r" % (off, kind, blk[5:18].split(b"\n")[0].decode("ascii", "replace")))
        else:
            print("    b%-3d %-12s %s" % (off, kind, blk[5:18].hex()))
    return ndtd


def check_predictions(b, ndtd):
    """Work out which timing path produced this EDID, then check it.

    The number of detailed timings and the presence of range limits identify
    the path, so decide that first and only then apply the checks that belong
    to it.
    """
    has_range = any(k == "RangeLimits" for _, k, _, _ in descriptors(b))
    d0 = dtd(b, 54)
    # These fields come from the static block and hold on every path
    std_blank = b[38:54] == b"\x01\x01" * 8
    std_dual = (b[38:44] == bytes.fromhex("d1c0d1ded1fc")
                and b[44:54] == b"\x01\x01" * 5)
    checks = [
        ("manufacturer id MRG (36 47)", mfg(b)[0] == "MRG" and b[8:10] == b"\x36\x47"),
        ("product code 0x3132", struct.unpack_from("<H", b, 10)[0] == 0x3132),
        ("week 8 / year 2023", b[16] == 8 and 1990 + b[17] == 2023),
        ("screen size 12x7 cm", (b[21], b[22]) == (12, 7)),
        ("established timings all zero", b[35:38] == b"\x00\x00\x00"),
        ("standard timings unused, or the dual-EDID 1920x1080 set",
         std_blank or std_dual),
        ("Monitor Name = 'Air'", b[108:126][5:18].split(b"\n")[0] == b"Air"),
        ("detailed timing bytes 12-14 hold active pixels (runtime builder)",
         bool(d0) and d0["idx12"] == (d0["ha"], d0["va"])),
    ]
    if ndtd == 3 and not has_range:
        # The first timing's vertical active tells stock 1080 lines from a
        # 1200-line build. The 1200 pixel clocks are 2200x1250 at 60/90/120.
        if d0 and d0["va"] == 1200:
            path = "mode 1 timing path: 1200 lines"
            table = ((54, 60, 165000), (72, 90, 247500), (90, 120, 330000))
            va = 1200
        else:
            path = "mode 1 timing path: stock 1080 lines"
            table = ((54, 60, 148500), (72, 90, 222750), (90, 120, 297000))
            va = 1080
        for off, hz, pclk in table:
            d = dtd(b, off)
            checks.append(("b%d = 1920x%d @%dHz pclk %d" % (off, va, hz, pclk),
                           bool(d) and (d["ha"], d["va"], d["pclk"]) == (1920, va, pclk)))
        if va == 1200:
            checks.append(("vertical totals close (1200+9+5+36 = 1250)",
                           bool(d0) and d0["va"] + d0["vfp"] + d0["vsw"] + d0["vbp"] == 1250))
        checks.append(("the third timing overwrites the range-limits descriptor", True))
    elif ndtd == 2 and has_range:
        path = "fixed-mode timing path (modes 3/4/5/8/9/10/11)"
        d1 = dtd(b, 72)
        checks.append(("the first two detailed timings are identical", b[54:72] == b[72:90]))
        checks.append(("range limits survive at byte 90", True))
        checks.append(("DTD = 1920x1080 / ht 2200 / vt 1125",
                       bool(d1) and (d1["ha"], d1["va"], d1["ht"], d1["vt"]) == (1920, 1080, 2200, 1125)))
        if d1:
            checks.append(("pixel clock %d matches %s" % (d1["pclk"], {148500: "60Hz", 178200: "72Hz",
                                                              222750: "90Hz", 297000: "120Hz"}
                                                  .get(d1["pclk"], "?")),
                           d1["pclk"] in (148500, 178200, 222750, 297000)))
    else:
        path = "unrecognised (%d detailed timings / range limits %s)" % (ndtd, "present" if has_range else "absent")
        checks.append(("matches neither known timing path", False))
    print("  --- timing path: %s ---" % path)
    print("  --- checks ---")
    ok = 0
    for name, res in checks:
        print("    [%s] %s" % ("OK" if res else "NG", name))
        ok += bool(res)
    print("    -> %d / %d passed" % (ok, len(checks)))
    return ok == len(checks)


def compare_rom(b):
    """Diff against the static ROM block, to show what the runtime builder changed."""
    if not os.path.exists(ROM):
        print("  (no stock container at %s, skipping the static-block diff)" % ROM)
        return
    rom = open(ROM, "rb").read()[ROM_STATIC_AIR:ROM_STATIC_AIR + 128]
    diff = [i for i in range(128) if rom[i] != b[i]]
    print("  --- diff against the static EDID at 0x%04X: %d bytes ---" % (ROM_STATIC_AIR, len(diff)))
    runs, cur = [], None
    for i in diff:
        if cur and i == cur[1] + 1:
            cur[1] = i
        else:
            cur = [i, i]
            runs.append(cur)
    for a, z in runs:
        where = ("DTD0 idx%d" % (a - 54) if 54 <= a < 72 else
                 "DTD1 idx%d" % (a - 72) if 72 <= a < 90 else
                 "b90 descriptor idx%d" % (a - 90) if 90 <= a < 108 else
                 "b108 descriptor" if 108 <= a < 126 else "byte%d" % a)
        print("    b%-3d..%-3d %-16s ROM %s -> HOST %s"
              % (a, z, where, rom[a:z + 1].hex(), b[a:z + 1].hex()))


def is_xreal(b):
    return len(b) >= 12 and mfg(b)[0] in ("MRG", "NRL")


def do_diff(tag_a, tag_b):
    pa = os.path.join(SCRATCH, "edid_%s.bin" % tag_a)
    pb = os.path.join(SCRATCH, "edid_%s.bin" % tag_b)
    for p in (pa, pb):
        if not os.path.exists(p):
            sys.exit("no such snapshot: %s" % p)
    a, b = open(pa, "rb").read(), open(pb, "rb").read()
    print("%s (%dB) vs %s (%dB)" % (tag_a, len(a), tag_b, len(b)))
    n = min(len(a), len(b))
    diff = [i for i in range(n) if a[i] != b[i]]
    if not diff and len(a) == len(b):
        print("  identical: the EDID did not change between these two")
        return
    print("  %d bytes differ" % len(diff))
    for i in diff:
        print("    b%-3d  %s: %02x   %s: %02x" % (i, tag_a, a[i], tag_b, b[i]))
    for tag, blob in ((tag_a, a), (tag_b, b)):
        nd = sum(1 for _, k, _, _ in descriptors(blob) if k == "DTD")
        hr = any(k == "RangeLimits" for _, k, _, _ in descriptors(blob))
        print("  %-10s %d detailed timings / range limits %s  -> %s"
              % (tag, nd, "present" if hr else "absent", "mode 1 path" if nd == 3 else "fixed-mode path"))


def main():
    argv = sys.argv[1:]
    if "--diff" in argv:
        i = argv.index("--diff")
        if len(argv) < i + 3:
            sys.exit("usage: --diff TAG_A TAG_B")
        return do_diff(argv[i + 1], argv[i + 2])

    tag = None
    if "--save" in argv:
        i = argv.index("--save")
        tag = argv[i + 1] if len(argv) > i + 1 else "snap"

    eds = get_edids()
    if not eds:
        sys.exit("could not read any EDID (this may need an elevated prompt)")
    act = active_instances()
    shown = 0
    for vendor, inst, b in eds:
        if not (is_xreal(b) or "--all" in argv):
            continue
        # WmiMonitorID instance names look like "DISPLAY\MRG3132\5&...&UID260_0".
        # Match on the vendor too, or stale entries sharing a UID look connected.
        key = ("DISPLAY\\%s\\%s" % (vendor, inst)).upper()
        active = any(a.startswith(key) for a in act)
        ndtd = show(vendor, inst, b, active)
        if ndtd is None:
            continue
        shown += 1
        if mfg(b)[0] == "MRG" and struct.unpack_from("<H", b, 10)[0] == 0x3132:
            check_predictions(b, ndtd)
            compare_rom(b)
            if tag and active:
                p = os.path.join(SCRATCH, "edid_%s.bin" % tag)
                open(p, "wb").write(b)
                print("  saved: %s" % p)
        print()
    others = len(eds) - shown
    if others and "--all" not in argv:
        print("(%d non-XREAL displays omitted; use --all to include them)" % others)


if __name__ == "__main__":
    main()
