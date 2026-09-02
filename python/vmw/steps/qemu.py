"""qemu step: patched QEMU build (from modules/qemu.sh).

Probes: /opt/vmw/emulator/bin/qemu-system-x86_64 (probe.sh).

Model-string spoofing lists moved to data/models.json; FACP parsing
moved to infra/firmware.py (struct reads replace dd/od). SMBIOS.bin
generation stays a subprocess (resources/scripts/Linux/SMBIOS.py is
never modified by this refactor).

Staleness: after install, the step records the patch SHA256 into
state.json (values.qemu.build_hash). vmw status compares it against
patches/checksums.sha256 and reports STALE (plan 01).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from vmw.infra.host import Host
from vmw.infra.probe import State, qemu_binary_present
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import PromptAnswers
from vmw.workflow.step import Step

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
OUT_DIR = Path("/opt/vmw")

QEMU_URI = "https://github.com/qemu/qemu.git"
QEMU_TAG = "v11.0.3"

# Optional, CPU-independent patch applied only when the profile exposes a
# vIOMMU (device.viommu). Defeats the DMAR table's QEMU IOAPIC signature.
DMAR_PATCH_NAME = "dmar-viommu-stealth.patch"

MODELS_FILE = Path(__file__).resolve().parent.parent / "data" / "models.json"
SMBIOS_SCRIPT = REPO_ROOT / "resources" / "scripts" / "Linux" / "SMBIOS.py"

# bash spoof_acpi() rewrite targets.
ACPI_APPNAME_HEADER = "include/hw/acpi/aml-build.h"
ACPI_BUILD_C = "hw/acpi/aml-build.c"
IDE_CORE_C = "hw/ide/core.c"
NVME_CTRL_C = "hw/nvme/ctrl.c"

CONFIGURE_ARGS = [
    "--target-list=x86_64-softmmu",
    "--prefix=/opt/vmw/emulator",
    "--without-default-features",
    "--enable-kvm",
    "--enable-linux-io-uring",
    "--enable-linux-aio",
    "--enable-pixman",
    "--enable-opengl",
    "--enable-sdl",
    "--enable-spice",
    "--enable-spice-protocol",
    "--enable-libusb",
    "--enable-libudev",
    "--enable-pipewire",
    "--enable-tpm",
    "--enable-numa",
    "--enable-seccomp",
    "--enable-zstd",
    "--enable-tools",
    "--enable-modules",
    "--disable-docs",
    "--disable-werror",
    "--disable-linux-user",
    "--disable-bsd-user",
    "--disable-tcg",
    "--extra-cflags=-g0",
    "--extra-ldflags=-s",
]


class QemuStep(Step):
    name = "qemu"
    title = "Build patched QEMU"

    def probe(self, host: Host) -> State:
        return State.DONE if qemu_binary_present() else State.MISSING

    def probe_detail(self, host: Host) -> str:
        path = "/opt/vmw/emulator/bin/qemu-system-x86_64"
        return f"{path} present" if qemu_binary_present() else f"{path} missing"

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []
        clone = SRC_DIR / QEMU_TAG
        patch_name = _patch_name(profile, host)

        # 0. reset-first [A5]. git clean alone only removes untracked
        # files; it leaves the previous build's patch applied in tracked
        # files, so the next git apply fails. Restore tracked files to
        # HEAD first, then clean, returning the tree to pristine.
        if _clone_exists():
            actions.append(
                Action(
                    key="qemu.reset",
                    cmd=["sh", "-c", "git restore --worktree :/ && git clean -fd"],
                    cwd=str(clone),
                    describe="reset QEMU tree to pristine HEAD (cancel hygiene [A5])",
                    always=True,
                )
            )

        # 1. packages
        from vmw.infra.packages import install_command, missing, packages_for

        pkgs = packages_for(host.distro, "qemu")
        need = missing(pkgs, host.distro)
        if need:
            actions.append(
                Action(
                    key="qemu.packages",
                    cmd=install_command(host.distro, need),
                    root=True,
                    describe=f"install {', '.join(need)}",
                )
            )

        # 2. acquire source
        if not _clone_exists():
            actions.append(
                Action(
                    key="qemu.clone",
                    cmd=["git", "clone", "--depth=1", "--branch", QEMU_TAG, QEMU_URI, QEMU_TAG],
                    cwd=str(SRC_DIR),
                    describe=f"clone QEMU {QEMU_TAG}",
                )
            )

        # 3. patch (integrity + drift via vmw.patches, then apply).
        # always=True: the reset above wipes the tree every build, so a
        # persisted "done" in state.json would be a lie - the patch is no
        # longer applied. Re-apply fresh each build; git apply is the
        # idempotency check against the now-pristine tree.
        actions.append(
            Action(
                key="qemu.patch",
                func=lambda ctx: _apply_patch(ctx, patch_name),
                describe=f"verify + apply patches/QEMU/{patch_name}",
                always=True,
            )
        )

        # 3b. DMAR stealth patch, only when the profile exposes a vIOMMU.
        # It strips the QEMU signature from the DMAR table that <iommu>
        # causes QEMU to emit. Without a vIOMMU there is no DMAR table,
        # so applying this would be pointless. always=True for the same
        # reset reason as qemu.patch.
        if profile.device.viommu:
            actions.append(
                Action(
                    key="qemu.patch_dmar",
                    func=lambda ctx: _apply_patch(ctx, DMAR_PATCH_NAME),
                    describe=f"apply patches/QEMU/{DMAR_PATCH_NAME} (vIOMMU DMAR stealth)",
                    always=True,
                )
            )

        # 4. spoofing. No model-string randomizer: the AMD/Intel patch
        # already rewrites every IDE/NVMe model string in hw/ide/core.c,
        # so the old spoof_models action has no stock string left to
        # replace and died on "not found". ACPI + SMBIOS spoofing remain.
        actions.append(
            Action(
                key="qemu.spoof_acpi",
                func=_spoof_acpi,
                describe="rewrite ACPI OEM/Creator IDs from host FACP",
            )
        )
        actions.append(
            Action(
                key="qemu.spoof_smbios",
                func=_spoof_smbios,
                describe="generate smbios.bin from host DMI (SMBIOS.py)",
            )
        )

        # 5. build + install
        actions.append(
            Action(
                key="qemu.configure",
                cmd=["./configure", *CONFIGURE_ARGS],
                cwd=str(clone),
                describe="configure QEMU (x86_64-softmmu, /opt/vmw/emulator)",
            )
        )
        actions.append(
            Action(
                key="qemu.build",
                cmd=["ninja", "-C", "build", "-j", _nproc()],
                cwd=str(clone),
                describe="compile QEMU (ninja)",
            )
        )
        actions.append(
            Action(
                key="qemu.install",
                cmd=["ninja", "-C", "build", "install"],
                cwd=str(clone),
                root=True,
                describe="install QEMU to /opt/vmw/emulator",
            )
        )

        # 6. record build hash for STALE detection
        actions.append(
            Action(
                key="qemu.build_hash",
                func=lambda ctx: _record_build_hash(ctx, patch_name),
                describe="record patch SHA256 into state.json (staleness)",
            )
        )

        return actions


def _clone_exists() -> bool:
    return (SRC_DIR / QEMU_TAG / "configure").is_file()


def _nproc() -> str:
    import os

    return str(os.cpu_count() or 1)


def _patch_name(profile: Profile, host: Host) -> str:
    from vmw.steps.patchsel import select_patch

    return select_patch("QEMU", profile.patches.qemu, f"{host.cpu_dir}-{QEMU_TAG}.patch")


def _apply_patch(ctx: RunContext, patch_name: str) -> None:
    # drift check (qemu.sh vmw::check_patch_drift)
    from vmw.steps.patchsel import verify_no_drift

    patch = verify_no_drift("QEMU", patch_name, QEMU_TAG)
    ctx.sh(["git", "apply", str(patch)], cwd=str(SRC_DIR / QEMU_TAG))
    ctx.log(f"applied {patch_name}")


def load_models(models_file: Path = MODELS_FILE) -> dict[str, list[str]]:
    with models_file.open() as handle:
        data = json.load(handle)
    return data


def pick_random_model(models: list[str], rng: random.Random | None = None) -> str:
    rng = rng or random
    return rng.choice(models)


def _spoof_models(ctx: RunContext) -> None:
    """modules/qemu.sh spoof_models(): random model strings per class.

    Dead: no longer planned. The AMD/Intel patch already rewrites all
    four stock strings below in hw/ide/core.c, so _replace_exact finds
    nothing and raises "not found". Kept only because models.json and
    test_models_json_loads still reference the data; safe to delete with
    them once model randomization is either dropped for good or rebuilt
    on the strings the patch now introduces.
    """
    models = load_models()
    rng = random.Random()

    new_cd = pick_random_model(models["ide_cd_models"], rng)
    new_cfata = pick_random_model(models["ide_cfata_models"], rng)
    new_default = pick_random_model(models["default_models"], rng)

    clone = SRC_DIR / QEMU_TAG
    _replace_exact(clone / IDE_CORE_C, "HL-DT-ST BD-RE WH16NS60", new_cd)
    _replace_exact(clone / IDE_CORE_C, "Hitachi HMS360404D5CF00", new_cfata)
    _replace_exact(clone / IDE_CORE_C, "Samsung SSD 980 500GB", new_default)
    _replace_exact(clone / NVME_CTRL_C, "NVMe Ctrl", new_default)
    ctx.log(f"spoofed models: cd={new_cd!r} cfata={new_cfata!r} default={new_default!r}")


def _replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(errors="surrogateescape")
    if f'"{old}"' not in text:
        raise RuntimeError(f"model string {old!r} not found in {path}")
    text = text.replace(f'"{old}"', f'"{new}"')
    with path.open("w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(text)


APPNAME6_RE = re.compile(r'(#define ACPI_BUILD_APPNAME6 )"[^"]*"')
APPNAME8_RE = re.compile(r'(#define ACPI_BUILD_APPNAME8 )"[^"]*"')


def spoof_acpi_files(
    clone: Path,
    facp: object,
) -> None:
    """modules/qemu.sh spoof_acpi(): rewrite OEM/Creator into aml-build."""
    header = clone / ACPI_APPNAME_HEADER
    text = header.read_text()
    text = APPNAME6_RE.sub(lambda m: f'{m.group(1)}"{facp.oem_id}"', text, count=1)
    text = APPNAME8_RE.sub(lambda m: f'{m.group(1)}"{facp.oem_table_id}"', text, count=1)
    header.write_text(text)

    build_c = clone / ACPI_BUILD_C
    ctext = build_c.read_text()
    ctext = ctext.replace('"ACPI"', f'"{facp.creator_id}"')
    build_c.write_text(ctext)


def _spoof_acpi(ctx: RunContext) -> None:

    facp = _read_facp(ctx)
    clone = SRC_DIR / QEMU_TAG
    spoof_acpi_files(clone, facp)
    ctx.log(
        f"spoofed ACPI: OEMID={facp.oem_id!r} OEMTableID={facp.oem_table_id!r} "
        f"CreatorID={facp.creator_id!r}"
    )

    if facp.preferred_pm_profile == 2:
        ctx.log("host FADT: Preferred_PM_Profile equals '2' (Mobile)")
        _spoof_acpi_mobile(ctx, clone)


def _read_facp(ctx: RunContext):
    """FACP via sudo (sysfs perms are root-only on this host)."""
    from vmw.infra.firmware import FACP

    return FACP.parse(ctx.read_root_bytes("/sys/firmware/acpi/tables/FACP"))


def _spoof_acpi_mobile(ctx: RunContext, clone: Path) -> None:
    """The mobile branch: PM profile rewrite + battery SSDT copy."""
    build_c = clone / ACPI_BUILD_C
    text = build_c.read_text()
    old = "1 /* Desktop */, 1"
    new = "2 /* Mobile */, 1"
    if old in text:
        text = text.replace(old, new, 1)
        build_c.write_text(text)
        ctx.log("PM profile rewritten to Mobile")

    # battery SSDT copy to /opt/vmw/firmware
    battery_ssdt = _find_battery_ssdt(ctx) or _find_battery_ssdt_root(ctx)
    if battery_ssdt:
        out = OUT_DIR / "firmware" / f"{battery_ssdt.name}-battery.aml"
        ctx.sh(["mkdir", "-p", str(OUT_DIR / "firmware")], root=True)
        ctx.sh(["cp", str(battery_ssdt), str(out)], root=True)
        ctx.sh(["chmod", "0644", str(out)], root=True)
        ctx.log(f"copied {battery_ssdt} to {out}")
    else:
        ctx.log("no SSDT containing battery info found; skipping battery SSDT copy")


def _find_battery_ssdt(ctx: RunContext) -> Path | None:
    """grep -aliE 'Battery|Capacity|Discharge|Charge' /sys/firmware/acpi/tables/SSDT*"""
    tables_dir = Path("/sys/firmware/acpi/tables")
    if not tables_dir.is_dir():
        return None
    pattern = re.compile(r"Battery|Capacity|Discharge|Charge", re.I)
    for ssdt in sorted(tables_dir.glob("SSDT*")):
        if not ssdt.is_file():
            continue
        try:
            blob = ssdt.read_bytes()
        except OSError:
            continue
        if pattern.search(blob.decode("ascii", "replace")):
            return ssdt
    return None


def _find_battery_ssdt_root(ctx: RunContext) -> Path | None:
    """Battery SSDT search when /sys is root-readable only (via sudo)."""

    tables_dir = Path("/sys/firmware/acpi/tables")
    if not tables_dir.is_dir():
        return None
    pattern = re.compile(r"Battery|Capacity|Discharge|Charge", re.I)
    listing = ctx.sh(["ls", str(tables_dir)], root=True)
    for name in sorted(n for n in listing.splitlines() if n.startswith("SSDT")):
        ssdt = tables_dir / name
        try:
            blob = ctx.read_root_bytes(ssdt)
        except PermissionError:
            continue
        if pattern.search(blob.decode("ascii", "replace")):
            return ssdt
    return None


def _spoof_smbios(ctx: RunContext) -> None:
    ctx.sh(["mkdir", "-p", str(OUT_DIR / "firmware")], root=True)
    ctx.sh(
        ["python3", str(SMBIOS_SCRIPT), "-o", str(OUT_DIR / "firmware" / "smbios.bin")],
        root=True,
    )
    ctx.log(f"generated smbios.bin to {OUT_DIR}/firmware")


def _record_build_hash(ctx: RunContext, patch_name: str) -> None:
    from vmw.steps.patchsel import record_build_hash

    record_build_hash(ctx, "qemu", "QEMU", patch_name)
