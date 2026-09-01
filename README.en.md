# nyan Real / Firmware Kit

Tooling that turns official firmware for display glasses and peripherals into guarded, locally built images.

*[日本語版はこちら / Japanese version](README.md)*

For display glasses, the kit exposes panel resolution, display modes, and audio
needed for **nyan Real / Spatial Wall**. For peripherals, it publishes reproducible,
hardware-tested compatibility fixes. The current targets are XREAL Air-family
glasses and a MOKIN UC6101B dock. Each builder is useful on its own even without
Spatial Wall.

> **nyan Real / Spatial Wall** is an application for using display glasses as a
> spatial display, on Windows, macOS, GNOME and Raspberry Pi. Only its manual is
> published so far; the application itself is not yet available.
> → [nyan-real-spatial-wall](https://github.com/8796n/nyan-real-spatial-wall)

**This project is not affiliated with, endorsed by, or connected to XREAL
(formerly Nreal), Rokid, MOKIN, or any other manufacturer.** Product and brand names are
used only to identify the hardware this tooling was written against. No vendor
code, branding, or firmware is distributed here.

---

## Read this before anything else

**Images produced by this tooling rewrite firmware on the target device. They can break it. You accept that
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
   tool cannot make a backup for you. Full firmware readback has not been
   established for Air 2 / Air 2 Pro, and this tooling provides no backup
   function for any supported model.

**If you use an Air (gen 1) with Nebula on an XREAL Beam Pro, do not flash the
Air build** — it stops working.
See [About XREAL's own apps](#about-xreals-own-apps) below.

We do not provide, host, mirror, or explain how to obtain vendor firmware, and we
will not answer questions asking for it. Issues and pull requests containing
firmware binaries or download links will be removed.

---

## What changes from the official firmware

The supported models are the XREAL Air (gen 1), Air 2, and Air 2 Pro, plus docks
built around the MOKIN UC6101B. Each XREAL update uses a matched **DP bridge and
MCU pair**. Air 2 and Air 2 Pro share both official inputs and kit outputs.

### XREAL Air (gen 1)

| Area | Official firmware | This build |
|---|---|---|
| Native RGB | Non-RGB OLED path | Displays native 2D and Full-SBS in RGB |
| Native resolution | `1920x1080` | Adds `1920x1200` as the preferred timing; `1920x1080` remains available |
| 720p | Not advertised in the EDID | Mode 1 advertises true `1280x720@60` and scales it to the full panel through the official YCbCr scaler path; fixed 72 / 90 / 120 Hz modes do not advertise it |
| Full-SBS | `3840x1080` at 60 / 72 Hz; a 90 Hz mode is present but does not work correctly because the link bandwidth is insufficient | `3840x1200` at 60 / 72 / 90 Hz; 90 Hz also works correctly |
| Audio without USB data | Manual switch or supported Adapter notification | After about five seconds, re-advertises an LPCM EDID and enters DP audio at the saved volume, with a blackout |
| HDMI hotplug while the converter stays powered | Some converters fail to restore video | Automatically restores video within several seconds after a temporary corrupted display |
| Power consumption | Baseline at the same timing and minimum brightness (setting 0) | About 0.18–0.19 W higher (+13–16%) |

Mode tables, timing details, audio routing, and other implementation details are documented in
[`xreal/air/docs/design.md`](xreal/air/docs/design.md) (Japanese only). Hardware
results are in [`xreal/air/docs/verification.md`](xreal/air/docs/verification.md)
(Japanese only).
Automatic DP audio and HDMI-hotplug recovery are results from the tested
converter, not a guarantee for every converter. On NVIDIA, sending a mode below
the preferred resolution as a true wire signal also requires display scaling to
be set to "none" for each EDID configuration.

### XREAL Air 2 / Air 2 Pro

| Area | Official firmware | This build |
|---|---|---|
| Native RGB | Non-RGB OLED path | Displays native 2D and Full-SBS in RGB |
| Native resolution | `1920x1080` | Remains `1920x1080` because the physical panel is 1080p |
| 720p | Not advertised in the EDID | Mode 1 advertises true `1280x720@60` and scales it to the full panel through the official YCbCr scaler path; fixed 72 / 90 / 120 Hz modes do not advertise it |
| Full-SBS | `3840x1080` at 60 / 72 Hz; a 90 Hz mode is present but does not work correctly because the link bandwidth is insufficient | `3840x1080` at 60 / 72 / 90 Hz; 90 Hz also works correctly |
| Audio without USB data | Manual switch or supported Adapter notification | After about five seconds, re-advertises an LPCM EDID and enters DP audio at the saved volume, with a blackout |
| HDMI hotplug while the converter stays powered | Some converters fail to restore video | Recovery logic is added; on Air 2 Pro it restores video within several seconds after a temporary corrupted display |
| Power consumption | Baseline at the same timing and minimum brightness (setting 0) | Air 2 measured about 0.17–0.18 W higher (about +14%); Air 2 Pro was not measured |

The shared design is in [`xreal/air2/docs/design.md`](xreal/air2/docs/design.md)
(Japanese only), and the hardware coverage is in
[`xreal/air2/docs/verification.md`](xreal/air2/docs/verification.md) (Japanese
only). Audio and hotplug compatibility is limited to the tested HDMI converter.
Powered HDMI hotplug was tested end to end on Air 2 Pro, not Air 2.

The power figures in both tables are whole-device USB input power with an identity
signal (`1920x1080@90` for Air and `1920x1080@60` for Air 2), minimum brightness,
and full-screen black or white. They are not measurements of an individual circuit.
As a trade-off of this build, including native RGB, power consumption is higher
than with the official firmware. Most of the additional input power ultimately
becomes heat, so more heat generation is expected under the same conditions.
Surface and internal temperature increases were not measured directly.

### What native RGB looks like

The official firmware names one panel path YCbCr, but its internal subsampling
has not been established. This README calls it **non-RGB** without guessing the
packing. This kit keeps native 2D and Full-SBS as RGB888 all the way to the OLED.

| This build: native RGB | Official firmware: non-RGB |
|---|---|
| ![Smooth native-RGB gradient](docs/assets/gradient-rgb.png) | ![Non-RGB gradient with diagonal scale-shaped contours](docs/assets/gradient-yuv.png) |

These are explanatory illustrations, not panel photographs. On shallow color
gradients, the diagonal contour steps are reduced and the image looks smoother.

### MOKIN UC6101B dock

| Area | Official firmware | This build |
|---|---|---|
| Switch 2 system version 21.x | Does not enter TV mode | TV mode and two simultaneous DisplayPort outputs hardware-verified |
| Nintendo VDM | Discards unknown commands without a response | Adds a type-`0x20` response and a protocol-reset pulse |
| Charging and resume | Baseline | 15 V / 2.6 A contract and sleep resume hardware-verified |

This builder only produces an Intel HEX image; it has no flashing support. See
the [design](peripherals/mokin/uc6101b/docs/design.md) and
[hardware verification](peripherals/mokin/uc6101b/docs/verification.md) for details.

---

## Preparation before flashing

### 1. Identify the model and official files

The builders accept the official inputs below and produce fixed outputs. The
hashes do not identify a download source; they only prove that your files match
the reviewed baseline.

| Model | Component | Official file location | Official input SHA-256 | Output SHA-256 |
|---|---|---|---|---|
| Air (gen 1) | DP | `firmware/1140` | `66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA` | `34AEE893AC697D314CB522D135AAE8C9222CC9461B62C096C616FEF44DE87AD8` |
| Air (gen 1) | MCU | `firmware/07.1.02.387_20240428.bin` | `B1784C6D618D3CF6F03D77A93442C3267A425CB2BE415E8912539E165645A3E7` | `F292B1245F2F26E209D6DACA6ADF50A58534B4EAEDC48C4FC8705703C879223D` |
| Air 2 / Air 2 Pro | DP | `firmware/air2/1140` | `350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3` | `46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486` |
| Air 2 / Air 2 Pro | MCU | `firmware/air2/09.1.00.180_20240507.bin` | `C07633E97215346468A18F5306A10F800388A80CCD7DCFE800D468F4AB1BFD49` | `950CA9535AFBD02C40D97A167DB06ECFAEEBC35F6ADCCDED81829CC44A8BE4C9` |
| MOKIN UC6101B | Intel HEX | `firmware/peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX` | `BE3C7FD831B7D3C1C6D822D70C72EACF2DA21958E03C6448A9857DB6D762AA7D` | `0DB0BF009776115FA890BDE71C6CC858CD102693A4B3D2CEF99F207826372CF1` |

Put the official files at those paths and keep another backup somewhere safe.
`firmware/` is gitignored, so its contents cannot be committed to this repository.

### 2. Install Python and dependencies

Use Python 3.10 or later. The builders use only the standard library. USB HID
tools for flashing, display-mode control, VSYNC, and register diagnostics require
`hidapi`.

```bash
pip install -r requirements.txt
```

PyPI also has a different package that provides `import hid`. Install `hidapi`,
which includes compiled bindings, and do not install both packages together.

### 3. Check the operating system and USB connection

Hardware flashing was verified on Windows. The pure-Python builders work on
Linux and macOS. HID tools are expected to work there but have not been tested.
Some display diagnostics are Windows-only.

| Operation | Windows | Linux / macOS |
|---|---|---|
| Build DP / MCU images | Supported | Supported |
| Build the UC6101B Intel HEX image | Supported | Supported |
| Flash DP / MCU images | Supported and hardware-verified | Untested |
| HID display and register diagnostics | Supported | Untested |
| EDID capture and Windows wire-signal inspection | Supported | Not supported |

`xreal/display.py --probe` invokes the Windows-only `edid_dump.py`, so that
option does not work on Linux or macOS. Normal mode reads and changes remain
untested HID operations there.

Connect only the target glasses directly to the PC before flashing. Disconnect
other XREAL or Nreal HID devices. On Linux, run as root or grant `hidraw` access,
for example:

```text
# /etc/udev/rules.d/70-xreal.rules
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3318", MODE="0666"
```

---

## What each script does

### Build images

| Script | Target | Writes hardware |
|---|---|---|
| `xreal/air/build_dp.py` | Air (gen 1) DP image | No |
| `xreal/air/build_mcu.py` | Air (gen 1) MCU image | No |
| `xreal/air2/build_dp.py` | Shared Air 2 / Air 2 Pro DP image | No |
| `xreal/air2/build_mcu.py` | Shared Air 2 / Air 2 Pro MCU image | No |
| `peripherals/mokin/uc6101b/build.py` | UC6101B Intel HEX image | No |

Each builder checks the official input SHA, every patch site's before bytes, the
resulting SHA, device-specific CRCs or checksums, and the complete change range.
Unexpected inputs or outputs are rejected. There is no `--force` option.

### Flash XREAL Air-family images

| Script | Purpose | When it writes |
|---|---|---|
| `xreal/dp_flash.py` | Inspect, flash, or restore the DP bridge | Only with `--flash` |
| `xreal/mcu_flash.py` | Verify, flash, or restore the MCU | Only with `--flash` |

Both tools bind the connected USB PID and model to exact known-image hashes,
validate the project code and container, and require the matching official
recovery image. Air 2 and Air 2 Pro share a project code, but their USB PIDs are
still checked separately. There is no bypass option.

### Inspect state

| Script | Purpose | Works on stock firmware |
|---|---|---|
| `common/display_signal.py` | Separates Windows desktop resolution from the active wire signal | Yes |
| `xreal/edid_dump.py` | Captures and decodes the EDID received by the host | Yes |
| `xreal/display.py` | Reads or changes Air-family logical display modes | Yes |
| `xreal/vsync.py` | Measures panel VSYNC | Yes |
| `xreal/dpreg.py` | Reads DP bridge registers | Requires this kit's MCU |
| `xreal/panelreg.py` | Reads or writes panel registers | Requires this kit's MCU |

`display.py` toggles HPD during a mode change, causing a short blackout.
`panelreg.py` writes panel RAM, so a full power cycle restores those values.

---

## Build the MOKIN UC6101B image

```bash
python peripherals/mokin/uc6101b/build.py \
  --src firmware/peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX \
  --out uc6101b-switch2.hex
```

This command never accesses hardware. Confirm the output SHA against the table
and keep the official image as your recovery path before flashing. See the
[UC6101B instructions](peripherals/mokin/uc6101b/README.md) for details.

---

## Build and flash XREAL Air-family images

Always use a DP and MCU pair for the same model. Run these commands from the
repository root.

### 1. Generate patched images

Air (gen 1):

```bash
python xreal/air/build_dp.py  --src firmware/1140                     --out air-dp.bin
python xreal/air/build_mcu.py --src firmware/07.1.02.387_20240428.bin --out air-mcu.bin
```

Air 2 / Air 2 Pro:

```bash
python xreal/air2/build_dp.py  --src firmware/air2/1140                     --out air2-dp.bin
python xreal/air2/build_mcu.py --src firmware/air2/09.1.00.180_20240507.bin --out air2-mcu.bin
```

Use `--check-only` to build and validate in memory without writing a file.

```bash
python xreal/air/build_dp.py --src firmware/1140 --check-only
```

Use `--verify` to prove that an existing file is byte-identical to the
deterministic output.

```bash
python xreal/air/build_dp.py --src firmware/1140 --verify air-dp.bin
```

### 2. Inspect the images before flashing

Running the DP tool without arguments only identifies the connected model and
reads the running DP version. It writes nothing.

```bash
python xreal/dp_flash.py
```

You can inspect generated images without `--flash`:

```bash
python xreal/dp_flash.py  --image air-dp.bin
python xreal/mcu_flash.py --image air-mcu.bin --verify-only
```

For Air 2 or Air 2 Pro, substitute `air2-dp.bin` and `air2-mcu.bin`. Do not
continue unless the reported model, SHA, CRC, and DP bank tag match the
preparation table.

### 3. Flash in the model-specific order

#### Air (gen 1): DP, then MCU

```bash
python xreal/dp_flash.py  --image air-dp.bin  --flash
python xreal/mcu_flash.py --image air-mcu.bin --flash
```

#### Air 2 / Air 2 Pro: MCU, then DP

```bash
python xreal/mcu_flash.py --image air2-mcu.bin --flash
python xreal/dp_flash.py  --image air2-dp.bin  --flash
```

Only calls carrying `--flash` send an update. Do not disconnect the cable or let
the PC sleep during transfer. The DP bridge restarts itself after FINISH, and
the MCU returns to its application through the bootloader, so a successful
write does not require a replug.

### 4. Check the result

Run `python xreal/dp_flash.py` again. The DP version should be `1140`. Version
`1109` means the bridge entered its fallback image; see
[If something goes wrong](#if-something-goes-wrong).

Test the resolutions, refresh rates, Full-SBS modes, and audio route you plan to
use. Use the diagnostic scripts above to record the active signal or EDID. The
container version string remains the official one, so track the modified state
with the generated SHA and your own records.

---

## Restore official XREAL Air-family firmware

The official files you saved must be at the paths in the preparation table.
Connect only the target glasses, then restore the MCU first and the DP bridge
second:

```bash
python xreal/mcu_flash.py --restore --flash
python xreal/dp_flash.py  --restore --flash
```

Recovery images are checked against the connected PID and the same fixed-hash
policy used for normal updates.

---

## About XREAL's own apps

**If you use an Air (gen 1) with Nebula on an XREAL Beam Pro, do not flash the
Air build. It stops working.**

Apps such as Nebula render with a correction that cancels lens distortion. The
required correction data exists only for 1080p. The Air build makes 1200p the
preferred timing, so Beam Pro Nebula cannot proceed past its startup screen.
This is hardware-verified, and restoring official firmware is the only remedy.
Normal use as an uncorrected external display is unaffected.

The build does not change the container version, so Nebula or Beam Pro will not
silently restore official firmware either.

Air 2 / Air 2 Pro keep `1920x1080` as the preferred timing, and both have been
hardware-tested for normal operation with XREAL Beam Pro.

On HDMI converter paths with no USB data, the full automatic DP-audio transition
closes the USB composite device. That connection did not have a USB data path in
the first place, so HID control is unavailable until the glasses are reconnected
to a USB-capable host.

---

## How the generated result is verified

The builders do more than apply patches. Every run verifies:

- the official input SHA-256, project code, and container CRC;
- every labelled change record's before bytes and allowed range;
- the deterministic output SHA-256, container CRC, DP bank0 tag, and changed-byte count;
- generated EDID checksums, DTDs, VICs, and per-mode advertisement contracts;
- all Air DP 8051 helper state vectors;
- the Air 2-family DP EDID and RGB-profile contracts; and
- the MCU display and recovery policy models; and
- UC6101B Intel HEX records, Block 1 CRC-8, image checksum, and changed-address set.

Detailed hardware results live in each model's `docs/verification.md`.
See [the container format](docs/container-format.en.md) and
[the HID protocol](docs/hid-protocol.en.md) for the shared technical details.

---

## If something goes wrong with an XREAL Air-family device

**You selected an image for another model.** The flasher refuses to send unless
the USB PID and fixed image SHA are an approved pair. Do not bypass the check;
verify the connected model and filename.

**The DP bridge starts its fallback image.** Symptoms are DP version `1109`,
monitor name `nreal air`, a fixed 60 Hz mode, and dead mode switching. The bank0
image was rejected, but this is recoverable. Flash the correct DP output again,
or restore the official DP image with `--restore`.

**The MCU application does not start.** If USB repeatedly connects and
disconnects, hold the button while connecting USB to enter the bootloader, then
restore the saved official MCU with `--restore --flash`.

**Transfer stopped or FINISH returned an error.** Do not retry in the same power
state. Disconnect and reconnect once to reset the MCU, then retry. A normally
completed write does not need a replug.

---

## Repository layout

```text
xreal/          XREAL Air-family HID, flashing, and diagnostic tools
  air/          Air (gen 1) builders and design/verification documents
  air2/         Shared Air 2 / Air 2 Pro builders and documents
peripherals/    Builders and design/verification documents for docks and adapters
common/         Model-independent display diagnostics
docs/           Container format, HID protocol, and common references
firmware/       Your official input files; gitignored
```

Models and firmware versions not listed above are unsupported. Do not reuse an
image on a similar model or another product with the same USB vendor id.

---

## License

Repository code and documentation are licensed under the
[Apache License 2.0](LICENSE).

That license does not cover vendor firmware processed by these tools. The
firmware remains the property of its rights holder and is not included here in
any form.

---

## Contributing

Bug reports and hardware results from supported models, as well as verifiable
support for new devices, are welcome. Results from untested operating systems or
hosts and values that differ from a model's `docs/verification.md` are especially useful.

**Do not post firmware binaries, download links, or requests for them.** Such
issues and comments will be removed without discussion.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
