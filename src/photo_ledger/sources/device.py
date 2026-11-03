"""Best-effort device details for a path: storage type, volume identifier, label, filesystem, size.

Nothing depends on these being known. Every lookup that fails leaves its field as ``None``.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

NETWORK_FILESYSTEMS = {"nfs", "nfs4", "cifs", "smbfs", "smb3", "sshfs", "fuse.sshfs", "afpfs", "9p"}
OPTICAL_FILESYSTEMS = {"iso9660", "udf", "cdfs"}

# GetDriveTypeW results.
_WINDOWS_DRIVE_TYPES = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "internal"}


@dataclass(frozen=True)
class DeviceInfo:
    source_type: str = "unknown"
    volume_id: str | None = None
    volume_root: str | None = None
    device_label: str | None = None
    filesystem: str | None = None
    capacity_bytes: int | None = None


def describe(path: Path) -> DeviceInfo:
    """Details of the volume holding ``path``. Never raises."""
    try:
        capacity = shutil.disk_usage(path).total
    except OSError:
        capacity = None
    try:
        details = _describe_windows(path) if sys.platform == "win32" else _describe_posix(path)
    except (OSError, ValueError, AttributeError):
        details = {}
    return DeviceInfo(capacity_bytes=capacity, **details)


def mounted_volumes() -> list[tuple[str, str]]:
    """``(volume_root, volume_id)`` for every mounted volume whose identifier can be read."""
    try:
        return _volumes_windows() if sys.platform == "win32" else _volumes_posix()
    except (OSError, ValueError, AttributeError):
        return []


# Windows ------------------------------------------------------------------------------------


def _kernel32():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Don't show "insert a disk" dialogs for empty card readers and optical drives.
    sem_failcriticalerrors = 0x0001
    kernel32.SetErrorMode(sem_failcriticalerrors)
    return kernel32


def _windows_volume_info(kernel32, volume_root: str) -> dict | None:
    import ctypes
    from ctypes import wintypes

    name = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    ok = kernel32.GetVolumeInformationW(
        volume_root, name, 261, ctypes.byref(serial), None, None, filesystem, 261
    )
    if not ok:
        return None
    return {
        "volume_id": f"{serial.value >> 16:04X}-{serial.value & 0xFFFF:04X}",
        "device_label": name.value or None,
        "filesystem": filesystem.value or None,
    }


def _describe_windows(path: Path) -> dict:
    import ctypes

    kernel32 = _kernel32()
    buffer = ctypes.create_unicode_buffer(261)
    if not kernel32.GetVolumePathNameW(str(path), buffer, 261):
        return {}
    volume_root = buffer.value
    details = {
        "volume_root": volume_root,
        "source_type": _WINDOWS_DRIVE_TYPES.get(kernel32.GetDriveTypeW(volume_root), "unknown"),
    }
    details.update(_windows_volume_info(kernel32, volume_root) or {})
    return details


def _volumes_windows() -> list[tuple[str, str]]:
    kernel32 = _kernel32()
    mask = kernel32.GetLogicalDrives()
    volumes = []
    for index in range(26):
        if mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            info = _windows_volume_info(kernel32, root)
            if info:
                volumes.append((root, info["volume_id"]))
    return volumes


# POSIX --------------------------------------------------------------------------------------


def _mounts() -> list[tuple[str, str, str]]:
    """``(device, mount_point, filesystem)`` from /proc/self/mounts, where it exists."""
    mounts = []
    with open("/proc/self/mounts", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) >= 3:
                # Spaces and tabs in mount points are octal-escaped.
                point = fields[1].encode().decode("unicode_escape")
                mounts.append((fields[0], point, fields[2]))
    return mounts


def _uuid_for(device: str) -> str | None:
    by_uuid = Path("/dev/disk/by-uuid")
    if not by_uuid.is_dir() or not device.startswith("/dev/"):
        return None
    target = os.path.realpath(device)
    for link in by_uuid.iterdir():
        if os.path.realpath(link) == target:
            return link.name
    return None


def _describe_posix(path: Path) -> dict:
    resolved = Path(path).resolve()
    best = None
    for device, point, filesystem in _mounts():
        if resolved.is_relative_to(point) and (best is None or len(point) > len(best[1])):
            best = (device, point, filesystem)
    if best is None:
        return {}
    device, point, filesystem = best
    if filesystem in NETWORK_FILESYSTEMS:
        source_type = "network"
    elif filesystem in OPTICAL_FILESYSTEMS:
        source_type = "optical"
    else:
        source_type = "unknown"
    return {
        "source_type": source_type,
        "volume_root": point,
        "volume_id": _uuid_for(device),
        "filesystem": filesystem,
    }


def _volumes_posix() -> list[tuple[str, str]]:
    volumes = []
    for device, point, _filesystem in _mounts():
        uuid = _uuid_for(device)
        if uuid:
            volumes.append((point, uuid))
    return volumes
