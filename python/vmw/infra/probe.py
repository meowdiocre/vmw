"""System predicates: is a step already in place? (from lib/probe.sh).

probe() implementations live in the steps; these are the shared
filesystem/service predicates they call. Pure functions of a Host +
filesystem layout. No side effects, unit-testable against fixture
trees.

State semantics (ADR-003): MISSING, PARTIAL, DONE, STALE.
"""

from __future__ import annotations

import re
import subprocess
from enum import Enum
from pathlib import Path


class State(Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    DONE = "done"
    STALE = "stale"


# Where vmw installs its artifacts (lib/probe.sh Vmw_OUT_DIR).
OUT_DIR = Path("/opt/vmw")


def _exists(path: Path) -> bool:
    """path.exists(), but a permission-denied path reads as absent.

    Python < 3.13 lets Path.exists()/is_file()/is_dir() propagate
    PermissionError (a root-only entry under /boot/efi, an /opt/vmw the
    user cannot stat); 3.13+ swallows it and returns False. Probes must
    read the same on every Python version and every machine, so any
    OSError here means "not present", never a crash.
    """
    try:
        return path.exists()
    except OSError:
        return False


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _try_run(argv: list[str], run: callable) -> subprocess.CompletedProcess[str] | None:
    """Run a probe command, returning None when the binary is absent.

    A pristine host (or container) may lack virsh/systemctl entirely;
    that must read as "not present", not crash probe_all.
    """
    try:
        return run(argv, capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return None


def libvirt_network_present(virsh: str = "virsh", run: callable = subprocess.run) -> bool:
    """vmw-Router network defined in libvirt (needs the daemon up)."""
    proc = _try_run([virsh, "--connect", "qemu:///system", "net-info", "vmw-Router"], run)
    return proc is not None and proc.returncode == 0


def libvirtd_active(run: callable = subprocess.run) -> bool:
    """libvirtd or the modular virtqemud daemon is running."""
    for unit in ("libvirtd", "virtqemud"):
        proc = _try_run(["systemctl", "is-active", "--quiet", unit], run)
        if proc is not None and proc.returncode == 0:
            return True
    return False


def kernel_boot_entry_present(kernel_tag: str, boot: Path = Path("/boot")) -> bool:
    """vmlinuz-<tag> in /boot OR an HvP-RDTSC boot entry (probe.sh)."""
    if _exists(boot / f"vmlinuz-{kernel_tag}"):
        return True
    for entry_dir in (
        boot / "loader/entries",
        Path("/boot/efi/loader/entries"),
        Path("/efi/loader/entries"),
    ):
        if _exists(entry_dir / "HvP-RDTSC.conf"):
            return True
    return False


def qemu_binary_present(out_dir: Path = OUT_DIR) -> bool:
    """Patched QEMU installed at <out>/emulator/bin/qemu-system-x86_64."""
    return _is_file(out_dir / "emulator/bin/qemu-system-x86_64")


def ovmf_firmware_present(out_dir: Path = OUT_DIR) -> bool:
    """OVMF_CODE.fd and OVMF_VARS.fd both present in <out>/firmware."""
    fw = out_dir / "firmware"
    return _is_file(fw / "OVMF_CODE.fd") and _is_file(fw / "OVMF_VARS.fd")


def vfio_bound(sys_root: Path = Path("/sys")) -> bool:
    """A PCI device is bound to vfio-pci, or the module is loaded."""
    drivers = sys_root / "bus/pci/drivers/vfio-pci"
    if _is_dir(sys_root / "kernel/iommu_groups") and _is_dir(drivers):
        try:
            entries = list(drivers.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d", entry.name):
                return True
    try:
        modules = (sys_root / "modules").read_text()
    except OSError:
        return False
    return re.search(r"^vfio[-_]pci\b", modules, re.M) is not None


def domain_defined(domain: str, virsh: str = "virsh", run: callable = subprocess.run) -> bool:
    """The domain from the profile is defined in libvirt."""
    proc = _try_run([virsh, "--connect", "qemu:///system", "dominfo", domain], run)
    return proc is not None and proc.returncode == 0


def patch_hash_stale(
    state_values: dict, step: str, patch_file: Path, checksums: Path
) -> State | None:
    """STALE check: build-time patch hash vs current checksums.sha256.

    Returns State.STALE when the step recorded a build hash that no
    longer matches the patch file on disk (lost-hunks regression
    guard, master plan "Staleness detection"). None when not
    applicable (no recorded hash -> caller falls back to its own
    probe).
    """
    recorded = state_values.get(f"values.{step}.build_hash")
    if not recorded:
        return None
    digest = _file_sha256(patch_file)
    if digest is None or digest != recorded:
        return State.STALE
    return None


def _file_sha256(path: Path) -> str | None:
    import hashlib

    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
