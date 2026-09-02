"""Host firmware readers: FACP struct parsing, DMI values, efivars.

Replaces the bash dd/od/uhex parsing from modules/{qemu,edk2}.sh with
struct reads. Pure functions of bytes; the privilege plumbing (reading
/sys/firmware/acpi/tables/FACP needs root) is the caller's job.

ACPI table layout reference: ACPI Spec 6.6 section 5.2.9 (FADT).
https://uefi.org/sites/default/files/resources/ACPI_Spec_6.6.pdf
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

FACP_PATH = Path("/sys/firmware/acpi/tables/FACP")
DMI_DIR = Path("/sys/class/dmi/id")
EFIVARS_DIR = Path("/sys/firmware/efi/efivars")

# Sub-tables whose iasl re-compiled .aml lives under patches/QEMU/.
PATCHES_QEMU_DIR = Path(__file__).resolve().parents[3] / "patches" / "QEMU"


class FirmwareReadError(RuntimeError):
    """A required host firmware value could not be read."""


@dataclass(frozen=True)
class FACP:
    """The FADT fields the spoofing needs (offsets per ACPI 6.6 §5.2.9)."""

    oem_id: str  # offset 10, 6 bytes
    oem_table_id: str  # offset 16, 8 bytes
    creator_id: str  # offset 28, 4 bytes
    oem_revision: int  # offset 24, u32
    creator_revision: int  # offset 32, u32
    preferred_pm_profile: int  # offset 45, u8

    @classmethod
    def parse(cls, data: bytes) -> FACP:
        if len(data) < 46:
            raise FirmwareReadError(f"FACP too short: {len(data)} bytes")
        return cls(
            oem_id=_ascii(data[10:16]),
            oem_table_id=_ascii(data[16:24]),
            creator_id=_ascii(data[28:32]),
            oem_revision=struct.unpack_from("<I", data, 24)[0],
            creator_revision=struct.unpack_from("<I", data, 32)[0],
            preferred_pm_profile=data[45],
        )

    @classmethod
    def read(cls, path: Path = FACP_PATH, reader: callable = None) -> FACP:
        """Read the FACP from sysfs (needs root on most systems)."""
        read = reader or (lambda p: p.read_bytes())
        try:
            data = read(path)
        except OSError as exc:
            raise FirmwareReadError(f"cannot read {path} (try sudo): {exc}") from exc
        return cls.parse(data)


def _ascii(raw: bytes) -> str:
    """ACPI strings: space-padded, NUL-terminated ASCII."""
    return raw.rstrip(b"\x00").decode("ascii", "replace").rstrip()


@dataclass(frozen=True)
class Dmi:
    """Host DMI values the firmware spoofing copies into OVMF."""

    bios_vendor: str
    bios_version: str
    bios_date: str
    bios_release: str  # "x.y"; PcdFirmwareRevision packs major.minor

    @classmethod
    def read(cls, dmi_dir: Path = DMI_DIR, reader: callable = None) -> Dmi:
        read = reader or (lambda p: p.read_text().strip())
        values = {}
        for field in ("bios_vendor", "bios_version", "bios_date", "bios_release"):
            path = dmi_dir / field
            try:
                values[field] = read(path)
            except OSError as exc:
                raise FirmwareReadError(f"cannot read {path}: {exc}") from exc
        return cls(
            bios_vendor=values["bios_vendor"],
            bios_version=values["bios_version"],
            bios_date=values["bios_date"],
            bios_release=values["bios_release"],
        )


def firmware_revision_u32(bios_release: str) -> int:
    """PcdFirmwareRevision from bios_release "major.minor".

    Packed (major << 16) | minor. This is the bash uhex 4-byte rule.
    """
    major, minor = _split_release(bios_release)
    return (major << 16) | minor


def u32_hex(value: int) -> str:
    """EDK2 PCD-style 0x%08X."""
    return f"0x{value:08X}"


def u64_hex(value: int) -> str:
    """EDK2 PCD-style 0x%016X."""
    return f"0x{value:016X}"


def ascii_hex(value: str, size: int) -> str:
    """ASCII bytes as little-endian hex u32/u64 PCD value.

    The bash uhex fallback: string bytes reversed (little-endian),
    space-padded to width. "EDK2" -> 0x324B4445.
    """
    raw = value.encode("ascii", "replace")[:size]
    padded = raw + b" " * (size - len(raw))
    return "0x" + padded[::-1].hex().upper()


def _split_release(release: str) -> tuple[int, int]:
    parts = release.split(".")
    try:
        major = int(parts[0]) if parts[0] else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        return 0, 0
    return major, minor


# Keys extracted from host efivars into the OVMF NVRAM (edk2.sh):
# name -> (guid, is_default). Defaults live in the same
# EFI_GLOBAL_VARIABLE namespace as their live counterparts.
EFI_GLOBAL_VARIABLE = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
EFI_IMAGE_SECURITY_DATABASE_GUID = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"

EFIVAR_KEYS: tuple[tuple[str, str, bool], ...] = (
    ("PK", EFI_GLOBAL_VARIABLE, False),
    ("KEK", EFI_GLOBAL_VARIABLE, False),
    ("db", EFI_IMAGE_SECURITY_DATABASE_GUID, False),
    ("dbx", EFI_IMAGE_SECURITY_DATABASE_GUID, False),
    ("PKDefault", EFI_GLOBAL_VARIABLE, True),
    ("KEKDefault", EFI_GLOBAL_VARIABLE, True),
    ("dbDefault", EFI_GLOBAL_VARIABLE, True),
    ("dbxDefault", EFI_GLOBAL_VARIABLE, True),
)


def read_efivars(efivars_dir: Path = EFIVARS_DIR, reader: callable = None) -> list[dict]:
    """Host EFI keys as virt-fw-vars --set-json entries.

    Each efivar file is: attributes (u32 LE) followed by the data.
    Root required. Returns only the keys that exist on this host.
    """
    read = reader or (lambda p: p.read_bytes())
    entries = []
    for name, guid, _is_default in EFIVAR_KEYS:
        path = efivars_dir / f"{name}-{guid}"
        if not path.is_file():
            continue
        try:
            blob = read(path)
        except OSError:
            continue
        if len(blob) < 4:
            continue
        attrs = struct.unpack_from("<I", blob, 0)[0]
        entries.append(
            {
                "name": name,
                "guid": guid,
                "attr": attrs,
                "data": blob[4:].hex(),
            }
        )
    return entries


def efivars_json(entries: list[dict]) -> str:
    """The exact JSON document virt-fw-vars --set-json expects."""
    lines = []
    for entry in entries:
        lines.append(
            '        {{ "name": "{}", "guid": "{}", "attr": {}, "data": "{}" }}'.format(
                entry["name"], entry["guid"], entry["attr"], entry["data"]
            )
        )
    return '{\n    "version": 2,\n    "variables": [\n' + ",\n".join(lines) + "\n    ]\n}\n"
