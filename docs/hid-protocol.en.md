# USB HID protocol — XREAL Air family

*[日本語版 / Japanese version](hid-protocol.md)*

This is how the tools under `xreal/` talk to the glasses. Reads and writes alike
ride the same 64-byte frame.

The implementation lives in `xreal/glasses.py` (framing, parsing, and device
identification).

**Scope.** The 64-byte frame format and DP write sequence (110–113) were
confirmed on the Air (gen 1), Air 2 / Air 2 Pro, and xbx a01+. The MCU write
message-id family is common to Air and P55, but their START splits differ. The
public DP and MCU flashers write Air, Air 2, and Air 2 Pro. Air 2 Pro uses the
same p55 images and transfer format as Air 2, with separate PID checks.

**XREAL One / One Pro / 1S do not use what is written here** -- they speak a
different protocol built on 16-bit ops, and the tools under `xreal/` do not work
on them.

Even within the same format, **which message ids are implemented differs per
device** (see below).

---

## Identifying the device

The VID is `0x3318` across XREAL products. The PID gives the model and its
state.

| PID | Model | State | Status in this kit |
|---|---|---|---|
| `0x0424` / `0x0423` | Air (gen 1) | APP / BOOT | verified |
| `0x0428` / `0x0427` | Air 2 | APP / BOOT | protocol and writes confirmed; writing supported |
| `0x0432` / `0x0431` | Air 2 Pro | APP / BOOT | shared Air 2 image writes confirmed; writing supported |
| `0x0441` / `0x0442` | xbx a01+ | APP / BOOT | same family, unverified |

The PID table in `xreal/glasses.py` exists **to identify what is plugged in**,
not as a list of supported devices. The One family (`0x0436`, `0x043E` and so
on) is deliberately not in it.

**APP and BOOT are MCU states, not DP bridge states.** Seeing BOOT only means
the MCU is sitting in its bootloader; the DP bridge runs independently of that.

The interface numbers are:

| Number | Purpose |
|---:|---|
| 3 | IMU |
| **4** | **control (MI_04); nearly every tool opens this one** |
| 5 | panel VSYNC notifications (endpoint `0x88`) |

**The bootloader is the exception: it exposes a single interface, IF0.**
Hard-coding `CTRL_IF` would miss BOOT forever, so `xreal/mcu_flash.py` picks
from the interfaces actually enumerated for that PID.

The kit's automatic no-USB DP-audio switch uses the same stock full transition
as manual audio selection and genuine Adapter Attention. It closes the USB
composite device and re-enumerates the EDID, so HID tools are unavailable after
that transition. Replugging through a USB-capable host restores USB audio and HID.

---

## Frame format

A 64-byte report on report id 0, zero padded.

```
[0]      0xFD              magic
[1:5]    CRC32-LE          covers [5 : 5+len)
[5:7]    len-LE            = 17 + payload length
[7:11]   seq
[11:15]  timestamp
[15:17]  msgId-LE
[17:22]  5 padding bytes
[22:]    payload           at most 42 bytes
```

**This CRC is the ordinary CRC-32, the same one zlib computes.** Do not confuse
it with the container CRC, which is a different polynomial entirely.

Responses come back in the same shape, with status at `[22]` and data after it.

```
msgId  = [15] | [16] << 8
status = [22]
data   = [23:]
```

**What counts as an ack differs by path.**

| Path | Status treated as ack |
|---|---|
| DP bridge PREPARE / START / TRANSMIT | `0` or `250` (`0xFA`) |
| DP bridge FINISH | `0` only |
| MCU write | `0` only |

The five bytes at `[17:22]` are padding; handlers skip them and read from `[22]`.

Never build a frame with an empty payload. A 16-byte frame (len `0x000B`)
crashes the xbx a01+ MCU. Whether the same happens on an Air has not been
checked.

`build_fd()` in `xreal/glasses.py` treats msgid as a single byte, so callers
hand it **six** padding bytes: the first becomes the high byte of msgId (always
zero) and the remaining five land in the padding above. The bytes on the wire
are identical either way.

---

## Writing the DP bridge

| msgid | Name | Payload |
|---:|---|---|
| 110 (`0x6E`) | PREPARE | empty |
| 111 (`0x6F`) | START | the first 64 bytes, split across two frames |
| 112 (`0x70`) | TRANSMIT | the rest, 42 bytes at a time |
| 113 (`0x71`) | FINISH | empty |

The sequence:

```
PREPARE(110)
START(111)     fw[0:42]
START(111)     fw[42:64]      the container header, split in two
TRANSMIT(112)  fw[64:] in 42-byte pieces  (1,204 of them for 50,632 bytes)
FINISH(113)    the MCU verifies the container CRC; a mismatch returns status 5
```

`xreal/dp_flash.py` writes Air, Air 2, and Air 2 Pro. Before writing, it requires a supported
PID paired with an exact known SHA-256 for that model, a valid container CRC and
bank0 tag, and the matching official stock recovery image. The shared
projectCode `0x0900` does not prove whether a device is Air 2 or Air 2 Pro.

**Once FINISH is acked, the bridge restarts itself and comes up on the new
image.** No replug is needed.

A failure is the one case that differs. If FINISH returns a bad status, times
out, or the transfer is interrupted, PREPARE does not reset the header count and
the SPI write offset, so **retrying within the same power session is unsafe.**
Unplug and replug first, then retry.

Repeating a successful write is safe. Nine consecutive writes to an Air without
a single replug all returned a FINISH ack and reported version `1140`.

---

## Writing the MCU

The MCU is written from the bootloader. **Only the application area is
rewritten, so a broken application can still be recovered from the bootloader.**

| msgid | Name | Payload |
|---:|---|---|
| 62 | PREPARE | empty |
| 68 | JUMP_TO_BOOT | empty |
| 63 | START | first 24 bytes on Air; first 64 bytes split 42+22 on P55 |
| 64 | TRANSMIT | bytes after START, 42 at a time |
| 65 | FINISH | empty |
| 66 | JUMP_TO_APP | empty |

The flasher's Air (gen 1) sequence is:

```
PREPARE(62)
JUMP_TO_BOOT(68)      no reply is awaited
[re-enumerates with the BOOT PID]
START(63)             fw[0:24]
TRANSMIT(64)          fw[24:] in 42-byte pieces
FINISH(65)            the bootloader verifies the container CRC
JUMP_TO_APP(66)
```

The flasher's P55 (Air 2 / Air 2 Pro) sequence is:

```
PREPARE(62)
JUMP_TO_BOOT(68)      wait for a status-0 ack
[re-enumerates with the BOOT PID]
START(63)             fw[0:42]
START(63)             fw[42:64]
TRANSMIT(64)          fw[64:] in 42-byte pieces
FINISH(65)            the bootloader verifies the container CRC
JUMP_TO_APP(66)
```

When the last TRANSMIT is shorter than 42 bytes, the official update procedure
sends that same short chunk once more. The flasher reproduces this on
both Air and P55. The current official Web updater sends `JUMP_TO_BOOT` once
through its response-wait helper on both models, then continues after either a
response or the roughly two-second timeout without using the returned status.
The flasher follows tested hardware behavior instead. On Air,
`JUMP_TO_BOOT` is **fired and forgotten.** Waiting for a reply both fails with
OSError and burns the window in which the bootloader accepts a transfer, since
it returns to the application if the update does not continue.
P55 instead waits for the status-0 `JUMP_TO_BOOT` ack before re-enumeration.

Timing measured on Air:

- the device disappears roughly 0.35 s after `JUMP_TO_BOOT`
- the BOOT PID appears at roughly 1.37 s
- **BOOT stays available for about 15 seconds.** Starting the transfer extends
  that, but do nothing else between there and `START`

**If the device is already in BOOT, PREPARE and JUMP_TO_BOOT are unnecessary.**
That is the recovery path when a broken application has left it stuck there;
`xreal/mcu_flash.py` detects BOOT and goes straight to the transfer, but only an
official stock image with an exact known SHA-256 matching the connected model
may be written. Normal writes likewise require a supported PID, an exact known SHA-256,
a valid container CRC, the matching official recovery image, and an APP msgid
38 version matching the reviewed baseline. They are limited to Air, Air 2, and
Air 2 Pro. Air 2 / Pro share the image but are checked against their separate
APP and BOOT PIDs.

---

## Reads

| msgid | Contents |
|---:|---|
| 22 | DP bridge firmware version |
| 38 | MCU application firmware version |
| `0x07` | current display mode |
| `0x08` | set display mode |

`0x07` returns **the current state of the DP link, not a readback of what you
wrote.** It also moves when the host changes refresh rate, so a value matching
what you sent with `0x08` is not by itself proof the switch took effect.

The display mode is volatile; a replug restores the default. Switching toggles
HPD, so the screen drops for a few seconds -- which is also what makes the host
re-read the EDID.

### The peeks this kit adds

Stock firmware offers the host no way to name a register address and read it.
The MCU build in this kit adds two.

| msgid | Target | Request | Response |
|---:|---|---|---|
| `0x29` | DP bridge register | `[0xA5, page, reg]` | one byte |
| `0x5B` | panel register | `[0xA5, eye, reg]` read | one byte |

**Against stock firmware the first times out and the second returns `0x23` for
every register.** `xreal/dpreg.py` and `xreal/panelreg.py` detect that and say
so, rather than reporting nonsense.

An early research image also had a generic panel write beginning with `0x5A`.
The public MCU reused that space for row-count helpers, so its msgid `0x5B` is
read-only and `xreal/panelreg.py` exposes no write. Model-specific experiments
that need one use a separately verified command with fixed target registers.

---

## Porting checklist

To extend this to another device, confirm things in this order.

1. **VID / PID and the interface layout** — which interface is control, and how
   many the bootloader exposes
2. **Whether the frame format matches** — magic `0xFD`, where the CRC sits and
   which CRC it is, how len is counted
3. **Whether the message ids match** — if a version read round-trips, the
   framing is right
4. **The container format** — see [container-format.en.md](container-format.en.md)
5. **The write procedure** — DP style (PREPARE/START/TRANSMIT/FINISH) or MCU
   style (drop into the bootloader)

Within the Air family, steps 1 to 3 are largely common. **Even within XREAL,
a different family will not follow this** -- One / One Pro / 1S use a separate
16-bit op protocol and share nothing with what is written here. Change vendor
and everything differs again: Rokid, for instance, uses USB control transfers
and standard DFU.
