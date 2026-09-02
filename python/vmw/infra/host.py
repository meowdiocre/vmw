"""Host detection: distro, CPU vendor, bootloader (from lib/host.sh).

Pure parsing functions over /etc/os-release, /proc/cpuinfo, and mount
metadata; the caller decides what to do with the answers.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Distro IDs accepted per family (lib/host.sh detect_distro).
_DISTRO_IDS: dict[str, set[str]] = {
    "Arch": {
        "arch",
        "manjaro",
        "endeavouros",
        "arcolinux",
        "garuda",
        "artix",
    },
    "openSUSE": {"opensuse", "sles", "opensuse-tumbleweed", "opensuse-leap"},
    "Fedora": {"fedora", "centos", "rhel", "rocky", "alma", "oracle"},
    "Debian": {
        "debian",
        "ubuntu",
        "linuxmint",
        "kali",
        "pop",
        "elementary",
        "zorin",
        "mx",
        "parrot",
        "deepin",
        "peppermint",
    },
}

# Command that identifies a distro family even when os-release is odd.
_DISTRO_TOOLS: dict[str, str] = {
    "Arch": "pacman",
    "openSUSE": "zypper",
    "Fedora": "dnf",
    "Debian": "apt",
}


@dataclass(frozen=True)
class Host:
    """Everything the steps need to know about the machine."""

    distro: str  # Arch | Debian | openSUSE | Fedora
    cpu_vendor: str  # GenuineIntel | AuthenticAMD
    cpu_manufacturer: str  # Intel | AMD
    cpu_virtualization: str  # vmx | svm
    bootloader: str  # grub | systemd-boot | limine | uki | unknown

    @property
    def cpu_dir(self) -> str:
        """Patch-selection directory name (Intel/AMD) used by qemu/edk2."""
        return self.cpu_manufacturer


class UnsupportedHostError(RuntimeError):
    """Raised when the host is not one vmw supports."""


def detect_distro(os_release: str | None = None, which: callable = shutil.which) -> str:
    """Return the distro family from /etc/os-release text.

    Pure: takes the os-release content (or reads it when None).
    """
    if os_release is None:
        try:
            os_release = Path("/etc/os-release").read_text()
        except OSError:
            os_release = ""

    distro_id = ""
    for line in os_release.splitlines():
        if line.startswith("ID="):
            distro_id = line.split("=", 1)[1].strip().strip('"').lower()
            break

    for family, ids in _DISTRO_IDS.items():
        if distro_id in ids:
            return family
    for family, tool in _DISTRO_TOOLS.items():
        if which(tool) is not None:
            return family
    raise UnsupportedHostError(f"Unsupported distribution: {distro_id or 'unknown'}")


def detect_cpu(cpuinfo: str | None = None) -> tuple[str, str, str]:
    """Return (vendor_id, manufacturer, virtualization flag) from /proc/cpuinfo."""
    if cpuinfo is None:
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
        except OSError:
            cpuinfo = ""

    if "GenuineIntel" in cpuinfo:
        return "GenuineIntel", "Intel", "vmx"
    if "AuthenticAMD" in cpuinfo:
        return "AuthenticAMD", "AMD", "svm"
    raise UnsupportedHostError("Unsupported CPU vendor.")


def _exists(path: Path) -> bool:
    """path.exists() with a permission-denied path read as absent.

    Same reason as infra/probe._exists: /boot/efi entries are often
    root-only, and Python < 3.13 raises PermissionError from exists()
    while 3.13+ returns False. Detection must not crash on either.
    """
    try:
        return path.exists()
    except OSError:
        return False


def _has_glob(path: Path, pattern: str) -> bool:
    try:
        return any(path.glob(pattern))
    except OSError:
        return False


def detect_bootloader(findmnt: callable = shutil.which, root: Path | None = None) -> str:
    """Return the bootloader type: grub|systemd-boot|limine|uki|unknown.

    Ported from modules/vfio.sh's bootloader detection: what mounts /boot
    or /efi (limine uses a different layout), plus the UKI check.
    """
    root = root or Path("/")

    # UKI: unified kernel images present in the ESP loader directory.
    if _exists(root / "boot/loader/entries") and _has_glob(root / "boot/EFI/Linux", "*.efi"):
        return "uki"

    # systemd-boot: entries dir + no GRUB config
    for entries in ("boot/loader/entries", "efi/loader/entries"):
        if _exists(root / entries):
            return "systemd-boot"

    if _exists(root / "boot/grub/grub.cfg") or _exists(root / "boot/grub2/grub.cfg"):
        return "grub"

    # Limine: limine.conf or limine-specific layout on the ESP.
    for conf in ("boot/limine.conf", "efi/limine/limine.conf"):
        if _exists(root / conf):
            return "limine"

    return "unknown"


def _mount_info(findmnt: callable) -> dict[str, str]:
    """fstab-less mount table via findmnt --json ({} on failure)."""
    if findmnt("findmnt") is None:
        return {}
    try:
        proc = subprocess.run(["findmnt", "--json"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return {}
        import json

        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError):
        return {}
    mounts: dict[str, str] = {}
    for fs in data.get("filesystems", []):
        for child in fs.get("children", []):
            source = child.get("source", "")
            target = child.get("target", "")
            if source and target:
                mounts[target] = source
    return mounts


def detect_host() -> Host:
    """Detect everything; raises UnsupportedHostError for odd machines."""
    vendor_id, manufacturer, virt_flag = detect_cpu()
    return Host(
        distro=detect_distro(),
        cpu_vendor=vendor_id,
        cpu_manufacturer=manufacturer,
        cpu_virtualization=virt_flag,
        bootloader=detect_bootloader(),
    )


# Boot-entry helper shared by kernel + vfio steps (from kernel.sh/vfio.sh).
BOOT_ENTRY_DIRS = (
    "/boot/loader/entries",
    "/boot/efi/loader/entries",
    "/efi/loader/entries",
)

KERNEL_TAG_RE = re.compile(r"vmlinuz-(linux\d+-tkg-[a-z]+)")
