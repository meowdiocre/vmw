"""edk2 step: patched OVMF build.

patch_ovmf() has three separate, probed, idempotent stages that each
run independently of the clone path. Skip logic is per-stage; probes
key on post-conditions, not tree paths.

- Patch apply: patches/EDK2/*.patch onto the edk2 clone. Probe: the
  tree's MdeModulePkg.dec contains the patch's marker rewrite (or a
  .patched marker written at apply time).
- Host metadata rewrite: firmware PCDs from host DMI + FACP. Probe:
  PcdFirmwareVendor in MdeModulePkg.dec equals host bios_vendor.
  PcdAcpiDefaultOemId keeps its quotes on rewrite; an empty or
  !=6-byte FADT OEM ID aborts the rewrite rather than writing junk.
- Logo replacement: Logo.bmp swap, with a backup taken before the
  swap. Probe: Logo.bmp sha256 != stock TianoCore hash.
- Build: BaseTools, edksetup, OVMF X64 RELEASE with SB+SMM+TPM.
- NVRAM injection: host efivars -> OVMF_VARS.fd via virt-fw-vars.
  OVMF_CODE.fd gets a backup taken before the swap
  (.pre-memfd.bak pattern).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from vmw.infra.host import Host
from vmw.infra.probe import State, ovmf_firmware_present
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import Prompt, PromptAnswers
from vmw.workflow.step import Step

if TYPE_CHECKING:
    from vmw.infra.firmware import FACP, Dmi

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
OUT_DIR = Path("/opt/vmw")

EDK2_URI = "https://github.com/tianocore/edk2.git"
EDK2_TAG = "edk2-stable202605"

BUILD_FV = "Build/OvmfX64/RELEASE_GCC/FV"

# Stock TianoCore MdeModulePkg/Logo/Logo.bmp hash. Placeholder until
# first build pins the real value (see docs detections/firmware.md).
STOCK_TIANYOCORE_LOGO_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"


class Edk2Step(Step):
    name = "edk2"
    title = "Build patched EDK2/OVMF"

    def probe(self, host: Host) -> State:
        if ovmf_firmware_present():
            return State.DONE
        return State.MISSING

    def probe_detail(self, host: Host) -> str:
        if ovmf_firmware_present():
            return "OVMF_CODE.fd + OVMF_VARS.fd in /opt/vmw/firmware"
        return "OVMF firmware missing in /opt/vmw/firmware"

    @staticmethod
    def _clone_path() -> Path:
        return SRC_DIR / EDK2_TAG

    def phase1_patch_applied(self, clone: Path | None = None) -> bool:
        """True once the patch is applied to the working tree."""
        clone = clone or self._clone_path()
        return clone.is_dir() and (clone / ".patched").exists()

    def phase2_metadata_done(self, clone: Path | None = None, bios_vendor: str = "") -> bool:
        """True once PcdFirmwareVendor equals host bios_vendor.

        Reads MdeModulePkg.dec, where the rewrite lands, not
        OvmfPkgX64.dsc.
        """
        clone = clone or self._clone_path()
        dec = clone / "MdeModulePkg/MdeModulePkg.dec"
        if not dec.is_file():
            return False
        try:
            text = dec.read_text(errors="replace")
        except OSError:
            return False
        if not bios_vendor:
            return 'PcdFirmwareVendor|L"EDK II"' not in text
        return f'PcdFirmwareVendor|L"{bios_vendor}"' in text

    def phase3_logo_done(self, clone: Path | None = None) -> bool:
        """True once Logo.bmp differs from stock TianoCore."""
        clone = clone or self._clone_path()
        logo = clone / "MdeModulePkg/Logo/Logo.bmp"
        if not logo.is_file():
            return False
        digest = hashlib.sha256(logo.read_bytes()).hexdigest()
        return digest != STOCK_TIANYOCORE_LOGO_SHA256

    def prompts(self, profile: Profile) -> list[Prompt]:
        return [
            Prompt(
                kind="choice",
                question="Boot logo source",
                choices=("host", "custom"),
                default="host",
                id="edk2.logo_source",
            ),
            Prompt(
                kind="path",
                question="Path to custom BMP logo (when logo_source=custom)",
                default="",
                id="edk2.logo_bmp",
            ),
        ]

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []
        clone = self._clone_path()
        patch_name = _patch_name(profile, host)

        # 0. reset-first [A5]. Restore tracked files to HEAD first; git
        # clean alone leaves a previous patch applied in tracked files.
        if clone.is_dir():
            actions.append(
                Action(
                    key="edk2.reset",
                    cmd=["sh", "-c", "git restore --worktree :/ && git clean -fd"],
                    cwd=str(clone),
                    describe="reset edk2 tree to pristine HEAD (cancel hygiene [A5])",
                    always=True,
                )
            )

        # 1. packages
        from vmw.infra.packages import install_command, missing, packages_for

        pkgs = packages_for(host.distro, "edk2")
        need = missing(pkgs, host.distro)
        if need:
            actions.append(
                Action(
                    key="edk2.packages",
                    cmd=install_command(host.distro, need),
                    root=True,
                    describe=f"install {', '.join(need)}",
                )
            )

        # 2. acquire source + patch
        if not clone.is_dir():
            actions.append(
                Action(
                    key="edk2.clone",
                    cmd=["git", "clone", "--depth=1", "--branch", EDK2_TAG, EDK2_URI, EDK2_TAG],
                    cwd=str(SRC_DIR),
                    describe=f"clone edk2 {EDK2_TAG}",
                )
            )
            actions.append(
                Action(
                    key="edk2.submodules",
                    cmd=["git", "submodule", "update", "--init", "--depth=1", "--jobs", _nproc()],
                    cwd=str(clone),
                    describe="init edk2 submodules",
                )
            )
        if not self.phase1_patch_applied(clone):
            actions.append(
                Action(
                    key="edk2.patch",
                    func=lambda ctx: _apply_patch(ctx, patch_name),
                    describe=f"verify + apply patches/EDK2/{patch_name}",
                )
            )

        # 3. metadata rewrite
        if not self.phase2_metadata_done(clone):
            actions.append(
                Action(
                    key="edk2.metadata",
                    func=_rewrite_metadata,
                    describe="rewrite firmware PCDs from host DMI/FACP (FADT guard)",
                )
            )

        # 4. logo replacement
        if not self.phase3_logo_done(clone):
            logo_source = answers.values.get("edk2.logo_source", "host")
            actions.append(
                Action(
                    key="edk2.logo",
                    func=lambda ctx: _replace_logo(ctx, logo_source, answers),
                    describe=f"replace Logo.bmp (source={logo_source}) with .bak backup",
                )
            )

        # 5. build
        actions.append(
            Action(
                key="edk2.basetools",
                cmd=["make", "-C", "BaseTools", "-j1"],
                cwd=str(clone),
                describe="build edk2 BaseTools",
            )
        )
        actions.append(
            Action(
                key="edk2.build",
                func=_build_ovmf,
                describe="build OVMF X64 RELEASE (SB+SMM+TPM)",
            )
        )

        # 6. install + NVRAM injection
        actions.append(
            Action(
                key="edk2.install",
                func=_install_firmware,
                describe="install OVMF fds + inject NVRAM (backup-before-swap)",
            )
        )

        # 7. build hash for STALE detection
        actions.append(
            Action(
                key="edk2.build_hash",
                func=lambda ctx: _record_build_hash(ctx, patch_name),
                describe="record patch SHA256 into state.json (staleness)",
            )
        )

        return actions


def _nproc() -> str:
    import os

    return str(os.cpu_count() or 1)


def _patch_name(profile: Profile, host: Host) -> str:
    from vmw.steps.patchsel import select_patch

    return select_patch("EDK2", profile.patches.edk2, f"{host.cpu_dir}-{EDK2_TAG}.patch")


def _apply_patch(ctx: RunContext, patch_name: str) -> None:
    from vmw.steps.patchsel import verify_no_drift

    patch = verify_no_drift("EDK2", patch_name, EDK2_TAG)
    clone = SRC_DIR / EDK2_TAG
    ctx.sh(["git", "apply", str(patch)], cwd=str(clone))
    (clone / ".patched").write_text("applied by vmw\n")
    ctx.log(f"applied {patch_name}")


def _rewrite_metadata(ctx: RunContext) -> None:
    """Rewrite firmware PCDs from host DMI + FACP.

    FADT-read guard: an empty or !=6-byte OEM ID aborts. ACPI
    requires exactly 6 bytes; junk is never written.
    """
    from vmw.infra.firmware import (
        ascii_hex,
        firmware_revision_u32,
        u32_hex,
    )

    dmi = _read_dmi(ctx)
    facp = _read_facp(ctx)

    # FADT-read guard: bail rather than write junk.
    if len(facp.oem_id.encode()) != 6:
        raise RuntimeError(
            f"FADT OEM ID is {len(facp.oem_id.encode())} bytes, expected 6: {facp.oem_id!r}"
        )

    clone = SRC_DIR / EDK2_TAG

    # --- SmbiosPlatformDxe.c: VendStr/VersStr/DateStr ---
    smbios_c = clone / "OvmfPkg/SmbiosPlatformDxe/SmbiosPlatformDxe.c"
    text = smbios_c.read_text()
    text = text.replace('VendStr = L"unknown";', f'VendStr = L"{dmi.bios_vendor}";')
    text = text.replace('VersStr = L"unknown";', f'VersStr = L"{dmi.bios_version}";')
    text = text.replace('DateStr = L"02/02/2022";', f'DateStr = L"{dmi.bios_date}";')
    smbios_c.write_text(text)

    # --- MdeModulePkg.dec PCD rewrites (quote-preserving) ---
    dec = clone / "MdeModulePkg/MdeModulePkg.dec"
    dec_text = dec.read_text()
    replacements = [
        # (PCD name, bash pattern, new value)
        (
            "PcdFirmwareVendor",
            'PcdFirmwareVendor|L"EDK II"|',
            f'PcdFirmwareVendor|L"{dmi.bios_vendor}"|',
        ),
        (
            "PcdFirmwareRevision",
            "PcdFirmwareRevision|0x00010000|",
            f"PcdFirmwareRevision|{u32_hex(firmware_revision_u32(dmi.bios_release))}|",
        ),
        (
            "PcdFirmwareVersionString",
            'PcdFirmwareVersionString|L""|',
            f'PcdFirmwareVersionString|L"{dmi.bios_version}"|',
        ),
        (
            "PcdFirmwareReleaseDateString",
            'PcdFirmwareReleaseDateString|L""|',
            f'PcdFirmwareReleaseDateString|L"{dmi.bios_date}"|',
        ),
        (
            "PcdAcpiDefaultOemId",
            'PcdAcpiDefaultOemId|"INTEL "|',
            f'PcdAcpiDefaultOemId|"{facp.oem_id}"|',
        ),
        (
            "PcdAcpiDefaultOemTableId",
            "PcdAcpiDefaultOemTableId|0x20202020324B4445|",
            f"PcdAcpiDefaultOemTableId|{ascii_hex(facp.oem_table_id, 8)}|",
        ),
        (
            "PcdAcpiDefaultOemRevision",
            "PcdAcpiDefaultOemRevision|0x00000002|",
            f"PcdAcpiDefaultOemRevision|{u32_hex(facp.oem_revision)}|",
        ),
        (
            "PcdAcpiDefaultCreatorId",
            "PcdAcpiDefaultCreatorId|0x20202020|",
            f"PcdAcpiDefaultCreatorId|{ascii_hex(facp.creator_id, 4)}|",
        ),
        (
            "PcdAcpiDefaultCreatorRevision",
            "PcdAcpiDefaultCreatorRevision|0x01000013|",
            f"PcdAcpiDefaultCreatorRevision|{u32_hex(facp.creator_revision)}|",
        ),
    ]
    for name, old, new in replacements:
        if old not in dec_text:
            raise RuntimeError(f"PCD anchor not found in MdeModulePkg.dec: {name}")
        dec_text = dec_text.replace(old, new, 1)
    dec.write_text(dec_text)
    ctx.log("rewrote firmware PCDs from host DMI/FACP")


def _read_dmi(ctx: RunContext) -> Dmi:
    """DMI via sudo (sysfs dmi files are root-readable only on this host)."""
    from vmw.infra.firmware import Dmi

    def reader(path: Path) -> str:
        return ctx.read_root_bytes(path).decode("utf-8", "replace").strip()

    return Dmi.read(reader=reader)


def _read_facp(ctx: RunContext) -> FACP:
    from vmw.infra.firmware import FACP

    return FACP.parse(ctx.read_root_bytes("/sys/firmware/acpi/tables/FACP"))


def _replace_logo(ctx: RunContext, logo_source: str, answers: PromptAnswers) -> None:
    """Swap Logo.bmp, backing up the stock file first."""
    import shutil

    clone = SRC_DIR / EDK2_TAG
    logo = clone / "MdeModulePkg/Logo/Logo.bmp"

    if logo_source == "custom":
        custom = answers.values.get("edk2.logo_bmp", "")
        if not custom or not Path(custom).is_file():
            raise RuntimeError(f"custom logo not found: {custom!r}")
        _validate_bmp(Path(custom))
        source = Path(custom)
        ctx.log(f"custom logo validated ({source})")
    else:
        bgrt = Path("/sys/firmware/acpi/bgrt/image")
        if not bgrt.is_file():
            raise RuntimeError(f"host BGRT image missing: {bgrt}")
        # BGRT image is root-readable only; stage it via sudo.
        import tempfile

        blob = ctx.read_root_bytes(bgrt)
        with tempfile.NamedTemporaryFile("wb", suffix=".bmp", delete=False) as handle:
            handle.write(blob)
            source = Path(handle.name)
        ctx.log("host BGRT logo staged")

    # back up the stock file before swapping it
    if logo.is_file():
        bak = logo.with_suffix(".bmp.bak")
        shutil.copy2(logo, bak)
        ctx.log(f"backed up stock logo to {bak.name}")

    shutil.copyfile(source, logo)
    ctx.log("Logo.bmp replaced")
    if logo_source != "custom":
        source.unlink(missing_ok=True)  # staged temp file


def _validate_bmp(path: Path) -> None:
    """edk2.sh validate_bmp(): magic/depth/compression/size checks."""
    header = path.read_bytes()[:54]
    if len(header) < 54:
        raise RuntimeError(f"BMP header too short: {path}")
    width = int.from_bytes(header[18:22], "little")
    height = int.from_bytes(header[22:26], "little")
    bit_depth = int.from_bytes(header[28:30], "little")
    compression = int.from_bytes(header[30:34], "little")
    if (
        header[0:2] != b"BM"
        or bit_depth not in (1, 4, 8, 24)
        or compression != 0
        or width > 65535
        or height > 65535
    ):
        raise RuntimeError(f"Invalid BMP: {width}x{height} @ {bit_depth}bpp (Comp: {compression})")


def _build_ovmf(ctx: RunContext) -> None:
    """Build BaseTools, then the OVMF X64 RELEASE image."""
    clone = SRC_DIR / EDK2_TAG
    build_cmd = [
        "build",
        "-p",
        "OvmfPkg/OvmfPkgX64.dsc",
        "-a",
        "X64",
        "-t",
        "GCC",
        "-b",
        "RELEASE",
        "-n",
        "0",
        "-s",
        "-D",
        "SECURE_BOOT_ENABLE=TRUE",
        "-D",
        "SMM_REQUIRE=TRUE",
        "-D",
        "TPM1_ENABLE=TRUE",
        "-D",
        "TPM2_ENABLE=TRUE",
    ]
    ctx.sh(build_cmd, cwd=str(clone))


def _install_firmware(ctx: RunContext) -> None:
    """Copy built .fd files into place and inject NVRAM.

    Existing /opt/vmw firmware is backed up before being replaced;
    OVMF_CODE.fd keeps the .pre-memfd.bak naming from the live tree.
    """

    clone = SRC_DIR / EDK2_TAG
    fv = clone / BUILD_FV
    code_src = fv / "OVMF_CODE.fd"
    vars_src = fv / "OVMF_VARS.fd"
    for src in (code_src, vars_src):
        if not src.is_file():
            raise RuntimeError(f"build output missing: {src}")

    fw_dir = OUT_DIR / "firmware"
    ctx.sh(["mkdir", "-p", str(fw_dir)], root=True)

    # back up existing artifacts before replacing them
    code_dst = fw_dir / "OVMF_CODE.fd"
    if code_dst.is_file():
        ctx.sh(["cp", str(code_dst), str(code_dst) + ".pre-memfd.bak"], root=True)
        ctx.log("backed up existing OVMF_CODE.fd to OVMF_CODE.fd.pre-memfd.bak")

    ctx.sh(["cp", str(code_src), str(code_dst)], root=True)

    # NVRAM injection via virt-fw-vars
    from vmw.infra.firmware import efivars_json

    entries = _read_efivars_root(ctx)
    payload = efivars_json(entries)

    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        handle.write(payload)
        json_path = handle.name
    try:
        ctx.sh(
            [
                "virt-fw-vars",
                "--input",
                str(vars_src),
                "--output",
                str(fw_dir / "OVMF_VARS.fd"),
                "--secure-boot",
                "--set-json",
                json_path,
            ],
            root=True,
        )
    finally:
        Path(json_path).unlink(missing_ok=True)
    ctx.log("Secure Boot provisioning complete")


def _read_efivars_root(ctx: RunContext) -> list[dict]:
    """Host EFI keys via sudo; returns virt-fw-vars JSON entries."""
    import struct

    from vmw.infra.firmware import EFIVAR_KEYS, EFIVARS_DIR

    entries = []
    for name, guid, _is_default in EFIVAR_KEYS:
        path = EFIVARS_DIR / f"{name}-{guid}"
        if not path.exists():
            continue
        try:
            blob = ctx.read_root_bytes(path)
        except PermissionError:
            continue
        if len(blob) < 4:
            continue
        attrs = struct.unpack_from("<I", blob, 0)[0]
        entries.append({"name": name, "guid": guid, "attr": attrs, "data": blob[4:].hex()})
    return entries


def _record_build_hash(ctx: RunContext, patch_name: str) -> None:
    from vmw.steps.patchsel import record_build_hash

    record_build_hash(ctx, "edk2", "EDK2", patch_name)
