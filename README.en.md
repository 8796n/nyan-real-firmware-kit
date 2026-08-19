# nyan Real / Firmware Kit

Firmware tooling that adapts display glasses for use with **nyan Real / Spatial Wall**.

*[日本語版はこちら / Japanese version](README.md)*

Display-only glasses often ship with firmware that never offers the panel's real
resolution, hides the best display mode, or leaves you with no audio on certain
sources. This repository collects what it takes, per model, to remove those
limits so the glasses work properly with Spatial Wall. **What that takes differs
per model:** some need a firmware build and a flash, others only need a
host-side tool to reach a capability the hardware already has. Either way the
result is useful on its own even if you do not use Spatial Wall.

> **nyan Real / Spatial Wall** is an application for using display glasses as a
> spatial display, on Windows, macOS, GNOME and Raspberry Pi. Only its manual is
> published so far; the application itself is not yet available.
> → [nyan-real-spatial-wall](https://github.com/8796n/nyan-real-spatial-wall)

**This project is not affiliated with, endorsed by, or connected to XREAL
(formerly Nreal), Rokid, or any other manufacturer.** Product and brand names are
used only to identify the hardware this tooling was written against. No vendor
code, branding, or firmware is distributed here.

---

## Read this before anything else

**This tool writes firmware to your glasses. It can break them. You accept that
risk entirely, or you do not use it.**

Three things are true at once, and you need all three:

1. **No firmware is distributed here — not the vendor's, and not the patched
   result.** A patched image is over 99% vendor code. You supply the official
   firmware yourself; this repository turns it into a patched image on your own
   machine.
2. **The official firmware file you obtain is your recovery path.** Keep it. Back
   it up somewhere you will still have it in a year. If you lose it and a flash
   goes wrong, this repository cannot help you.
3. **Whether the device can be read back depends on the model. Do not count on
   it.** For the XREAL Air (gen 1) it is **confirmed impossible**: static
   analysis of the stock MCU application found no host-facing message id that
   exposes an address-and-length read of the application or boot region, so the
   tool cannot make a backup for you. Other models are covered in their own
   sections.

**If you use Nebula on an XREAL Beam Pro, do not flash this** -- it stops working.
See [About the vendor's own apps](#about-the-vendors-own-apps) below.

We do not provide, host, mirror, or explain how to obtain vendor firmware, and we
will not answer questions asking for it. Issues and pull requests containing
firmware binaries or download links will be removed.

---

## Supported devices

| Device | Status |
|---|---|
| XREAL Air (gen 1) | **supported**, both the DP bridge and the MCU |
| XREAL Air 2 | planned, 720p support first |
| Rokid Max | planned. Likely host-side display-mode control rather than a firmware change (see below) |
| xbx a01 family | planned |

What each model needs, and how it was verified, lives in that model's directory.
Everything below describes the currently supported XREAL Air (gen 1).

### About Rokid Max (planned)

Rokid Max is a different situation. **Its EDID does not live in the MCU firmware
but in the DP bridge (LT7911UX)**, whose firmware is neither published nor
dumpable. The kind of EDID rewrite done for the XREAL Air is therefore not
possible.

What is possible is better: **the best display mode already exists in the
hardware.** `3840x1200@90` (per eye `1920x1200@90`) can be selected over a USB
control transfer, but the official SDK exposes only the two lowest modes and the
button on the glasses cannot reach it either. That is the gap worth closing.

The STM32 MCU can be both dumped and written over DFU, so firmware work remains
possible there if it turns out to be needed. Note that obtaining the latest
official MCU firmware requires a Rokid Station 2; the version bundled with the
phone app is older.

---

## What you need — XREAL Air (gen 1)

| Component | File | SHA-256 |
|---|---|---|
| DP bridge | `1140` | `66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA` |
| MCU | `07.1.02.387_20240428.bin` | `B1784C6D618D3CF6F03D77A93442C3267A425CB2BE415E8912539E165645A3E7` |

These are the official Air (gen 1) images. The hashes are published so you can
verify that whatever you obtained is the exact file this tooling expects — the
builders refuse to run on anything else.

### Python

Python 3.10+. **What you need to install depends on what you are doing.**

| Task | Requires |
|---|---|
| Building an image | **nothing** -- standard library only |
| Reading the EDID or the Windows display signal | **nothing** -- it reads what the OS already knows |
| Flashing, or reading registers | `hidapi` |

```bash
pip install -r requirements.txt
```

Two different PyPI packages provide `import hid`. **The one you want is `hidapi`**,
which ships a compiled binding. The other, named `hid`, is a ctypes wrapper that
needs a system libhidapi installed separately. Installing both leads to confusing
import errors.

### Operating systems

**Verified on Windows.**

| Tool | Windows | Linux / macOS |
|---|---|---|
| `xreal/air/build_dp.py` / `build_mcu.py` | works | **works** (pure Python) |
| `xreal/dp_flash.py` / `mcu_flash.py` | works | should work, untested |
| `xreal/display.py` / `dpreg.py` / `panelreg.py` / `vsync.py` | works | should work, untested |
| `xreal/edid_dump.py` | works | **no** -- uses PowerShell and WMI |
| `common/display_signal.py` | works | **no** -- uses the Windows display-config API |

Building an image works anywhere. The tools that talk to the glasses use nothing
but hidapi, so they ought to work on Linux and macOS, but that has not been
checked here.

`xreal/display.py --probe` calls `edid_dump.py` after switching, so that one
combination needs Windows. Reading and setting the mode works on any OS.

**On Linux you need permission to reach the HID device.** Run as root, or install
a udev rule.

```
# /etc/udev/rules.d/70-xreal.rules
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3318", MODE="0666"
```

---

## What it does — XREAL Air (gen 1)

Stock firmware advertises 1080p and nothing else. The panels are actually
1920x1200, that geometry is never offered, sources limited to 720p get no
matching timing, and sources that carry no USB data get no audio at all. This
kit makes all four input paths work.

| Input | Stock | With this build |
|---|---|---|
| `1280x720` | no matching timing | **VIC 4 advertised in the CTA.** The bridge scales it to full screen |
| `1920x1080` | native | unchanged, 60 / 90 / 120 Hz |
| `1920x1200` | never offered | **the preferred timing**, 60 / 90 / 120 Hz |
| `3840x1200` Full-SBS | `3840x1080` | **3840x1200 @ 60 / 72 / 90 Hz** over HBR2 |

Per logical mode:

| Logical mode | Stock | With this build |
|---:|---|---|
| 1 (auto) | `1080p60/90/120` | **`1200p60` preferred**, `1200p90`, `1200p120`, plus `1080p60/90/120` and `720p60` in the CTA block |
| 5 / 10 / 11 (fixed refresh) | `1080p` only | **`1200p72/90/120` preferred**, same-refresh `1080p` alternate, no CTA leak |
| 3 / 4 / 9 (Full-SBS 3D) | `3840x1080` | **`3840x1200` @ 60 / 72 / 90 Hz** over HBR2 |

Every 2D mode advertises 1920x1200 as the EDID preferred timing, so hosts that
derive "native resolution" from the preferred timing — macOS in particular — pick
1200p by default instead of never offering it at all.

The panel row count, the panel timing group, the DP link rate and the input
classifier all follow the actual input signal automatically. Changing resolution
or refresh rate on the host needs no action on the glasses.

### Automatic DP audio

**HDMI-to-USB-C converters and consoles carry no USB data.** USB audio is
impossible, and there is nobody to press the button for a manual switch. On
stock firmware, getting sound in that situation takes either a long-press by the
user or a genuine Nreal Adapter asserting a dedicated bit.

The MCU in this build watches the USB `SET_ADDRESS` sticky word:

- if the host ever addresses the device, it **stays on USB audio** for that power
  session, so a directly connected PC never falls into DP audio by mistake
- only if the address stays zero for roughly five seconds does it enter the stock
  DP-audio transition
- the genuine Nreal Adapter attention path fires immediately, as it does on stock
- the saved volume level is restored on the transition, and the manual toggle is
  locked for the rest of the power session

Note that **entering DP audio closes the USB composite device — that is stock
behaviour** — so HID control is unavailable while DP audio is active.

**Known host-side caveat.** NVIDIA's driver GPU-scales any mode smaller than the
display's native resolution. Now that native is 1200p, selecting 1080p may be
stretched rather than sent as a true 1080p signal. Setting scaling to "none" in
the NVIDIA control panel fixes it — but that setting is stored per EDID
configuration, so it must be set once per logical mode you care about. If you run
at 1200p, none of this affects you.

XREAL's stock container carries EDID templates for several models and the
header's project code selects one; the Air (gen 1) builder touches only the Air
template and leaves the others byte-identical to stock.

---

## About the vendor's own apps

**If you use Nebula on an XREAL Beam Pro, do not flash this. It stops working.**

Apps that render into the glasses, Nebula among them, draw with a correction
applied to cancel the lens distortion, and **that correction data exists only
for 1080p.** At 1200p the rendering never comes together and the app does not
get past its launch screen. This was confirmed on hardware.

**There is no way around it.** The Beam Pro follows the EDID preferred timing,
so you cannot drop it to 1080p from the host and carry on. Going back to stock
is the only option.

**Using the glasses as an external display is unaffected.** For anything that
sends a plain image without optical correction -- an ordinary desktop, and the
use this kit is built for -- 1200p is simply better.

### Nothing reverts behind your back

This build does not touch the container header, so the firmware version the
glasses report stays as stock. Nebula and the Beam Pro do not see a device that
needs updating and will not push firmware at it.

### No app can talk to the glasses during DP audio

The USB composite device closes, which is stock behaviour -- but this build
enters DP audio automatically on sources that carry no USB data, so you meet it
more often than on stock. Replugging clears it.

### Going back to stock

```bash
python xreal/dp_flash.py  --restore --flash
python xreal/mcu_flash.py --restore --flash
```

Both need the stock file present in `firmware/`.

---

## Usage

**The DP bridge and the MCU are a pair.** Flashing only one of them leaves the
panels not following the input, or the audio not switching. Do both.

Build both images from your own stock files:

```bash
python xreal/air/build_dp.py  --src firmware/1140                     --out air-dp.bin
python xreal/air/build_mcu.py --src firmware/07.1.02.387_20240428.bin --out air-mcu.bin
```

The builders verify as they go, and any mismatch is a hard failure — there is no
`--force`. Check without writing anything:

```bash
python xreal/air/build_dp.py --src firmware/1140 --check-only
```

The builders produce a fixed output. If your SHA-256 matches the table below,
what you built is byte-identical to what was verified here.

| Image | SHA-256 |
|---|---|
| DP | `D5D34FB0ED0AB49B92D793CCF8384E61B1C1274AAC45293911F3CAF325BDC793` |
| MCU | `3842A4232356B993CFDE839B3D772EB861FC382B0506EF2098E1352F100A77FE` |

Then flash. **This is the irreversible part.**

```bash
python xreal/dp_flash.py  --image air-dp.bin  --flash
python xreal/mcu_flash.py --image air-mcu.bin --flash
```

The DP bridge restarts itself after FINISH, so no replug is needed. The MCU
returns to its application through the bootloader.

Running `xreal/dp_flash.py` with no arguments is safe: it identifies the
connected glasses and prints the running firmware version without writing
anything. Do that first.

---

## Why you can trust the build

The builder does not just apply a patch. It proves the result:

- the stock input must match the expected SHA-256, project code and container CRC
- the change set is a table of explicit before/after records, each labelled — you
  can audit it by diffing the two images yourself
- every record's "before" bytes must match before it is applied
- the build is deterministic, and the output SHA-256, container CRC, bank0 commit
  tag and changed-byte count are all pinned
- the resulting EDID is decoded and checked against the advertised contract for
  every logical mode
- the firmware's own 8051 post-build helper is executed in a small emulator over
  every possible state vector, to prove which EDID timing slots each mode writes

Design notes and the full hardware acceptance record live in `xreal/air/docs/`.
Those two are **Japanese only**; the protocol and container references under
`docs/` are available in both languages.

---

## If something goes wrong

These are the failure modes that have actually been observed, and how they were
recovered.

**Wrong project code.** The container header carries a project code that selects
the model. Writing an image built for another model can destroy the glasses. Both
the builder and the flasher refuse on mismatch. Do not defeat this.

**DP bridge boots the fallback image.** If the bank0 commit tag does not match,
the bridge rejects bank0 and falls back to an internal image. Symptoms: reported
version `1109`, monitor name `nreal air`, stuck at 60 Hz, mode switching dead.
**This is recoverable** — reflash a good image with the same tool.

**MCU will not start.** A bad MCU image can leave the application unable to boot;
the device enumerates and disconnects in a loop. Hold the button while connecting
USB to enter the bootloader (PID `0x0423`), then write the stock MCU image back in
full. This has been done successfully and the device recovered completely.

**A transfer aborted or FINISH returned a bad status.** Unplug and replug to reset
before retrying. A normal successful write needs no replug; the bridge restarts
itself.

---

## Layout

```
xreal/          XREAL-common: HID protocol, flashing, diagnostics
  air/          Air (gen 1) builders and design/acceptance docs
common/         vendor-neutral tools
docs/           container format, protocol notes, shared background
firmware/       where you put the stock files you obtained (gitignored)
```

**What lives under `xreal/` targets the Air family.** It is verified on the Air
(gen 1), and the Air 2 and Air 2 Pro speak the same USB HID protocol
(VID `0x3318`).

**Sharing a VID does not mean the tools apply.**

| Device | Tools under `xreal/` |
|---|---|
| Air (gen 1) | verified |
| Air 2 / Air 2 Pro | same protocol, not verified here |
| XREAL One / One Pro / 1S | **do not work.** A different protocol built on 16-bit ops |
| xbx a01+ (x by XREAL) | same protocol family, with differences in detail; unverified |

Rokid is further away still, using USB control transfers and DFU, and will get
its own `rokid/` directory.

`common/` holds only things that know nothing about any device. Right now that
is one tool, which reports whether Windows is sending the desktop resolution to
the wire or scaling it.

The flashers check the model identifier in the container header, so an image
built for one model cannot be written to another by mistake.

### Diagnostics

None of these write firmware. What they need differs, though:

| Tool | Works on stock firmware | What it does |
|---|---|---|
| `common/display_signal.py` | yes, any display | desktop mode vs the signal on the wire |
| `xreal/edid_dump.py` | yes | decode the EDID the host received, diff snapshots |
| `xreal/display.py` | yes | read and switch the logical display mode |
| `xreal/vsync.py` | yes | measure the panel VSYNC rate |
| `xreal/dpreg.py` | **no** | read DP bridge registers |
| `xreal/panelreg.py` | **no** | read and write panel registers |

`dpreg.py` and `panelreg.py` need the MCU image built by this kit, which adds a
register peek that stock firmware does not have. Against stock firmware the
first times out and the second reads `0x23` everywhere; both say so rather than
reporting nonsense.

Two of them are not purely passive. `display.py` toggles HPD when it switches,
so the screen drops for a few seconds -- the mode itself is volatile and a
replug restores the default. `panelreg.py` can write, but panel registers live
in RAM, so a power cycle undoes anything done there.

---

## License

The code and documentation in this repository are licensed under [LICENSE](LICENSE).

**This license does not extend to the vendor firmware the tooling operates on.**
That firmware is the property of its owner, is not included here in any form, and
its licensing is between you and the vendor.

---

## Contributing

Bug reports and hardware test results are welcome, especially from devices,
operating systems or host setups that have not been tested here -- and
especially when you measure something different from the tables in
`xreal/air/docs/verification.md`.

**Do not post firmware binaries, download links, or requests for either.** Such
issues and comments will be removed without discussion.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the details.
