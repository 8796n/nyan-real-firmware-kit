# Firmware container format — Air family / xbx a01 family

*[日本語版 / Japanese version](container-format.md)*

The DP bridge image and the MCU image are both wrapped in the same kind of small
container: a header carrying a CRC, a size and some identity, then the payload.

This document exists so you can read what `xreal/air/build_dp.py` and
`xreal/air/build_mcu.py` are checking, and what `xreal/dp_flash.py` refuses to
write.

**There is more than one container.** Two shapes turned up across the images
examined here.

| Shape | Header | CRC stored | Images using it |
|---|---|---|---|
| **A (the usual one)** | `0x40` bytes, carries projectCode and fwType | LE | DP images for Air / Air 2 / xbx a01+ (fwType 2), MCU images for Air 2 / xbx a01+ (fwType 1) |
| **B** | 24 bytes, no projectCode and no fwType | BE | **the Air (gen 1) MCU image** |

**Only the Air (gen 1) MCU uses shape B,** and it is the sole exception found so
far. The Air 2 and xbx a01+ MCU images use shape A, even though they are also
"MCU firmware". Check each device-and-role combination for itself.

**And the same container does not mean the same contents.** The xbx a01+ DP
image is wrapped in a shape-A container, but how its payload holds EDID is
nothing like the Air family (see below). Being able to read the container says
nothing about the structure inside it.

**XREAL One / One Pro / 1S are a different architecture, and there is no
evidence they use either shape.** They appear in the projectCode table below
because that table lives inside Air-family firmware -- not because their own
firmware comes in this container.

---

## The DP bridge container

The first `0x40` bytes are the header and the payload follows. **The size
differs per image** (`1140` for Air / Air 2 is `50,632` bytes; `001C` for
xbx a01+ is `59,866`). The header layout is common.

| Offset | Size | Contents |
|---|---:|---|
| `0x00` | 4 | container CRC-32 (**stored little-endian**) |
| `0x04` | 4 | length, little-endian; sets the CRC's range |
| `0x08` | 4 | projectCode -- which model this image is for |
| `0x0C` | 4 | fwType; the DP bridge is `2` |
| `0x10` | 20 | name, NUL terminated; `"1140"` for the DP image |
| `0x24` | 14 | build string |
| `0x38` | 1 | **bank0 commit tag** |
| `0x40` | — | payload |

**Code addresses map to file offsets as `code = file - 0x40`.** The payload is
8051 code, so "code 0x1148" in a document or a comment means file `0x1188`.

### The container CRC-32

```
poly       0xF4ACFB13
init       0
reflect    neither input nor output
xorout     0
covers     d[8 : 8+length]
stored at  d[0:4], little-endian
```

Both the polynomial and the reflection differ from the common CRC-32. The
standard library's `zlib.crc32` will not reproduce it.

### The bank0 commit tag

**This is the one that matters most.** The DP7911 boot verifies this tag and
rejects bank0 if it does not match.

```
poly       0x31 (CRC-8)
init       0
MSB first, no reflection, xorout 0
covers     the payload (file 0x40..EOF) padded with 0xFF up to 0xFFFF bytes
stored at  d[0x38]
```

The boot's own test is whether the CRC-8 over all of bank0, tag included, comes
out zero: append the one tag byte to the padded payload, take the CRC-8, and
zero means it passes.

**What happens when the tag does not match.** The bridge discards bank0 and
starts from a fallback image held outside it. The symptoms are:

- the firmware version reads `1109` instead of `1140`
- the monitor name becomes `nreal air`
- the refresh rate sticks at 60 Hz and mode switching stops working

**This is recoverable.** Write a good image again with the same tool. The
bootloader itself is not damaged.

### projectCode

**The projectCode in the header is the only thing that identifies the model.
Neither the file name nor the name field tells you anything.** An image named
`1140` exists both for the Air (projectCode `0x0700`) and for the Air 2 /
Air 2 Pro (`0x0900`); the payloads are nearly identical and the projectCode is
what separates them.

| projectCode | Model |
|---|---|
| `0x0700` | Air (gen 1) |
| `0x0900` | Air 2 / Air 2 Pro |
| `0x1200` | Air 2 Ultra |
| `0x1500` | XREAL One / One Pro |
| `0x1900` | xbx a01+ |

**This is the table Air-family firmware carries internally.** It is not the list
of devices this kit supports, nor a claim that those models use this container
format. The only image verified by the builders is the Air (gen 1).

**Writing an image whose projectCode belongs to another model can destroy the
glasses.** The builders refuse an unexpected projectCode, and the flasher
compares the image's projectCode against the one derived from the connected
device's PID, aborting on a mismatch.

### How EDID is held differs per payload

**From here on this is no longer about the container, but about what is inside
an Air / Air 2 family payload.** Two payloads can share a container and still
hold EDID completely differently. The xbx a01+ `001C`, for instance, has
**neither** the multi-model table nor the runtime timing synthesis described
below (its EDID buffer is 512 bytes and extension blocks pass through
untouched).

#### Several models' EDID templates live side by side (Air / Air 2 family)

The payload carries a 128-byte static EDID block per model.

| File offset | Model | Monitor name |
|---|---|---|
| `0x1D5C` | Air (gen 1) | `Air` |
| `0x1DDC` | HONOR Glass | `HONOR Glass` |
| `0x1E5C` | Air 2 | `Air 2` |
| `0x1EDC` | Air 2 Pro | `Air 2 Pro` |
| `0x1F5C` | Air 2 Ultra | `Air 2 Ultra` |

Which one is served is selected at runtime from a model id. **The Air builder in
this kit modifies only the block at `0x1D5C` and leaves every other model's
block byte-identical to stock.**

#### Static template and runtime builder (Air / Air 2 family)

What the host receives is not that static block verbatim. The firmware assembles
the detailed timings at runtime, writes them into the block, and recomputes the
checksum afterwards.

There is a way to tell. Bytes 12-14 of a detailed timing normally hold the
physical screen size in mm, but the runtime builder puts **the active pixel
counts** there instead. `xreal/edid_dump.py` detects this and says which it
found.

The XDATA layout is:

```
0x022B   start of the base EDID block
 +54     DTD slot 0   (0x0261)
 +72     DTD slot 1   (0x0273)
 +90     DTD slot 2   (0x0285)
 +108    DTD slot 3   (0x0297)
 +126    extension block count
 +128    CTA extension block (0x02AB)
```

Slot 3 holds the monitor name descriptor; how slot 2 is used depends on the
mode.

This XDATA layout and the timing synthesis were confirmed on the Air (gen 1).
**Do not expect the same layout in a different payload.**

---

## The MCU container

**The shape depends on the model.**

### Air (gen 1) — shape B

Fixed at `153,888` bytes. The header is 24 bytes, and **the endianness differs
from the DP container.**

| Offset | Size | Contents |
|---|---:|---|
| `0x00` | 4 | container CRC-32 (**stored big-endian**) |
| `0x04` | 4 | length, little-endian; `0x25918` = filesize - 8 |
| `0x08` | 16 | name; `"Air.BootV_0.0.1"` |
| `0x18` | — | payload |

**There is no projectCode and no fwType.** The name is the only identity, and
`xreal/air/build_mcu.py` checks that it starts with `"Air."`.

The CRC polynomial and range match the DP container (`poly 0xF4ACFB13`,
`d[8 : 8+length]`); **only the storage is big-endian.** The bank0 commit tag is
a DP bridge boot mechanism and does not appear in an MCU container.

### Air 2 — shape A

`151,160` bytes. **The header is the same standard shape as a DP image,** CRC
stored little-endian included.

| Offset | Contents |
|---|---|
| `0x00` | container CRC-32 (stored little-endian) |
| `0x04` | length; `0x24E70` |
| `0x08` | projectCode `0x0900` (Air 2 / Air 2 Pro) |
| `0x0C` | **fwType `1`** (a DP image is `2`) |
| `0x10` | name; `"09.1.00.180_2024..."` |

**fwType is what separates DP from MCU.** Since a projectCode is present, model
matching works exactly as it does for DP images.

Given that two devices' "MCU firmware" can differ this much, **read the first 32
bytes of the header before anything else when approaching a new device** and
work out which shape you are holding.

The payload is ARM Thumb code beginning with a vector table.

```
VA          = file offset + 0xEFE8
file offset = VA - 0xEFE8
```

The mapping is confirmed from that vector table: the first two words at
`file 0x18` are the initial stack pointer `0x2001C9E8` and the reset vector
`0x0000F259`; with the Thumb bit removed, `0xF258` maps to `file 0x270`, and
that offset does decode as real code.

Besides the container CRC, `xreal/air/build_mcu.py` also checks that the initial
stack pointer lies in SRAM and that the reset vector points inside the payload.

---

## The order things are checked

Both the builders and the flashers confirm the same things in the same order
before going further.

1. **Size** — does it match the fixed length for that device and role
2. **Identity** — projectCode and fwType for shape A, the name for shape B
3. **Container CRC** — does the header value match a recomputation
   (**mind the storage endianness**)
4. **bank0 tag** (DP only) — is it a value the boot will accept
5. **SHA-256** — is this exactly a known image

Steps 1 to 4 **can be decided from the image alone**, so they work on a file of
unknown provenance. Step 5 is what says whether it is an image this kit has
verified.

The flashers additionally check that **the connected device's projectCode
matches the image's.** They do not write on a mismatch.
