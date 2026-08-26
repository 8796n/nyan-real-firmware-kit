#!/usr/bin/env python3
"""Show the Windows desktop mode and the signal actually on the wire, separately.

Windows can hand the GPU one resolution and put a different one on the cable:
that is what ``scaling`` reports. A value of 1 means identity, so the desktop
mode is what leaves the port; anything else means the GPU is stretching. When
checking whether the glasses really receive a mode, this distinction is the
whole point -- ``desktop=`` is what the OS thinks, ``active=`` is what the
glasses see.

Read-only. Windows only.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W

QDC_ONLY_ACTIVE_PATHS = 0x2
GET_SOURCE_NAME = 1
GET_TARGET_NAME = 2
TARGET_NAME_EDID_IDS_VALID = 0x4
PATH_ACTIVE = 0x1
TARGET_IN_USE = 0x1
AIR_EDID_MANUFACTURER_RAW = 0x4736
AIR_EDID_PRODUCT = 0x3132


class LUID(C.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class RATIONAL(C.Structure):
    _fields_ = [("Numerator", W.UINT), ("Denominator", W.UINT)]


class POINTL(C.Structure):
    _fields_ = [("x", W.LONG), ("y", W.LONG)]


class REGION(C.Structure):
    _fields_ = [("cx", W.LONG), ("cy", W.LONG)]


class SOURCE_INFO(C.Structure):
    _fields_ = [("adapterId", LUID), ("id", W.UINT), ("modeInfoIdx", W.UINT),
                ("statusFlags", W.UINT)]


class TARGET_INFO(C.Structure):
    _fields_ = [("adapterId", LUID), ("id", W.UINT), ("modeInfoIdx", W.UINT),
                ("outputTechnology", W.UINT), ("rotation", W.UINT), ("scaling", W.UINT),
                ("refreshRate", RATIONAL), ("scanLineOrdering", W.UINT),
                ("targetAvailable", W.BOOL), ("statusFlags", W.UINT)]


class PATH_INFO(C.Structure):
    _fields_ = [("sourceInfo", SOURCE_INFO), ("targetInfo", TARGET_INFO), ("flags", W.UINT)]


class VIDEO_SIGNAL_INFO(C.Structure):
    _fields_ = [("pixelRate", C.c_uint64), ("hSyncFreq", RATIONAL), ("vSyncFreq", RATIONAL),
                ("activeSize", REGION), ("totalSize", REGION), ("videoStandard", W.UINT),
                ("scanLineOrdering", W.UINT)]


class TARGET_MODE(C.Structure):
    _fields_ = [("targetVideoSignalInfo", VIDEO_SIGNAL_INFO)]


class SOURCE_MODE(C.Structure):
    _fields_ = [("width", W.UINT), ("height", W.UINT), ("pixelFormat", W.UINT),
                ("position", POINTL)]


class MODE_UNION(C.Union):
    _fields_ = [("targetMode", TARGET_MODE), ("sourceMode", SOURCE_MODE)]


class MODE_INFO(C.Structure):
    _fields_ = [("infoType", W.UINT), ("id", W.UINT), ("adapterId", LUID),
                ("modeInfo", MODE_UNION)]


class DEVICE_HEADER(C.Structure):
    _fields_ = [("type", W.UINT), ("size", W.UINT), ("adapterId", LUID), ("id", W.UINT)]


class SOURCE_NAME(C.Structure):
    _fields_ = [("header", DEVICE_HEADER), ("viewGdiDeviceName", W.WCHAR * 32)]


class TARGET_NAME(C.Structure):
    _fields_ = [
        ("header", DEVICE_HEADER),
        ("flags", W.UINT),
        ("outputTechnology", W.UINT),
        ("edidManufactureId", W.USHORT),
        ("edidProductCodeId", W.USHORT),
        ("connectorInstance", W.UINT),
        ("monitorFriendlyDeviceName", W.WCHAR * 64),
        ("monitorDevicePath", W.WCHAR * 128),
    ]


def active_paths() -> list[dict]:
    u = C.WinDLL("user32", use_last_error=True)
    u.GetDisplayConfigBufferSizes.argtypes = [W.UINT, C.POINTER(W.UINT), C.POINTER(W.UINT)]
    u.GetDisplayConfigBufferSizes.restype = W.LONG
    u.QueryDisplayConfig.argtypes = [W.UINT, C.POINTER(W.UINT), C.POINTER(PATH_INFO),
                                     C.POINTER(W.UINT), C.POINTER(MODE_INFO), C.c_void_p]
    u.QueryDisplayConfig.restype = W.LONG
    u.DisplayConfigGetDeviceInfo.argtypes = [C.POINTER(DEVICE_HEADER)]
    u.DisplayConfigGetDeviceInfo.restype = W.LONG

    path_count, mode_count = W.UINT(), W.UINT()
    rc = u.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS,
                                       C.byref(path_count), C.byref(mode_count))
    if rc:
        raise SystemExit(f"GetDisplayConfigBufferSizes failed: {rc}")
    paths = (PATH_INFO * path_count.value)()
    modes = (MODE_INFO * mode_count.value)()
    rc = u.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, C.byref(path_count), paths,
                              C.byref(mode_count), modes, None)
    if rc:
        raise SystemExit(f"QueryDisplayConfig failed: {rc}")

    result = []
    for path in paths[:path_count.value]:
        source_name = SOURCE_NAME()
        source_name.header.type = GET_SOURCE_NAME
        source_name.header.size = C.sizeof(source_name)
        source_name.header.adapterId = path.sourceInfo.adapterId
        source_name.header.id = path.sourceInfo.id
        if u.DisplayConfigGetDeviceInfo(C.byref(source_name.header)):
            continue

        target_name = TARGET_NAME()
        target_name.header.type = GET_TARGET_NAME
        target_name.header.size = C.sizeof(target_name)
        target_name.header.adapterId = path.targetInfo.adapterId
        target_name.header.id = path.targetInfo.id
        if u.DisplayConfigGetDeviceInfo(C.byref(target_name.header)):
            continue

        source = modes[path.sourceInfo.modeInfoIdx].modeInfo.sourceMode
        signal = modes[path.targetInfo.modeInfoIdx].modeInfo.targetMode.targetVideoSignalInfo
        hz = (signal.vSyncFreq.Numerator / signal.vSyncFreq.Denominator
              if signal.vSyncFreq.Denominator else 0.0)
        result.append({
            "device": source_name.viewGdiDeviceName,
            "desktop": (source.width, source.height),
            "active": (signal.activeSize.cx, signal.activeSize.cy),
            "total": (signal.totalSize.cx, signal.totalSize.cy),
            "refresh": hz,
            "pixel": signal.pixelRate,
            "scaling": path.targetInfo.scaling,
            "path_flags": path.flags,
            "target_available": bool(path.targetInfo.targetAvailable),
            "target_status": path.targetInfo.statusFlags,
            "target_name_flags": target_name.flags,
            "manufacturer": target_name.edidManufactureId,
            "product": target_name.edidProductCodeId,
            "friendly_name": target_name.monitorFriendlyDeviceName,
            "monitor_path": target_name.monitorDevicePath,
        })
    return result


def air_signal() -> dict:
    matches = [
        item for item in active_paths()
        if item["path_flags"] & PATH_ACTIVE
        and item["target_available"]
        and item["target_status"] & TARGET_IN_USE
        and item["target_name_flags"] & TARGET_NAME_EDID_IDS_VALID
        and item["manufacturer"] == AIR_EDID_MANUFACTURER_RAW
        and item["product"] == AIR_EDID_PRODUCT
        and item["friendly_name"] == "Air"
        and item["monitor_path"].upper().startswith(r"\\?\DISPLAY#MRG3132#")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one active Air display path, found {len(matches)}")
    return matches[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("display", nargs="?",
                    help=r"e.g. \\.\DISPLAY2; omit to list every active path")
    args = ap.parse_args()

    found = False
    for item in active_paths():
        if args.display and item["device"].upper() != args.display.upper():
            continue
        print(f"{item['device']}: desktop={item['desktop'][0]}x{item['desktop'][1]}; "
              f"active={item['active'][0]}x{item['active'][1]}; "
              f"total={item['total'][0]}x{item['total'][1]}; "
              f"refresh={item['refresh']:.3f}Hz; pixel={item['pixel']}; "
              f"scaling={item['scaling']}")
        found = True
    if args.display and not found:
        raise SystemExit(f"active path not found: {args.display}")


if __name__ == "__main__":
    main()
