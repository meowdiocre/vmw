"""vfio step: GPU passthrough (from modules/vfio.sh).

Probes: vfio-pci binding / module loaded (probe.sh).

The bash flow (revert -> configure -> bootloader -> rebuild) becomes
prompts + probe-gated actions. GPU selection is a device Prompt fed
from lspci. IOMMU group validation ports the "poor grouping" guard.
The cmdline edits for GRUB/systemd-boot/UKI/Limine are pure text
transforms (unit-testable), applied via root file writes.
"""

from __future__ import annotations

import re
from pathlib import Path

from vmw.infra.host import Host
from vmw.infra.probe import State, vfio_bound
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import Prompt, PromptAnswers
from vmw.workflow.step import Step

VFIO_CONF_PATH = Path("/etc/modprobe.d/vfio.conf")

VFIO_KERNEL_OPTS_REGEX = re.compile(r"(intel_iommu=[^ ]*|iommu=[^ ]*|vfio-pci\.ids=[^ ]*)")
LIMINE_ENTRY_REGEX = re.compile(r"^KERNEL_CMDLINE\[.*\]\+?=")

SDBOOT_CONF_LOCATIONS = (
    "/boot/loader/entries",
    "/boot/efi/loader/entries",
    "/efi/loader/entries",
)

GPU_DRIVERS: dict[str, str] = {
    "0x10de": "nouveau nvidia nvidia_drm",
    "0x1002": "amdgpu radeon",
    "0x8086": "i915 xe",
}


class VfioStep(Step):
    name = "vfio"
    title = "Configure GPU passthrough"

    def probe(self, host: Host) -> State:
        return State.DONE if vfio_bound() else State.MISSING

    def probe_detail(self, host: Host) -> str:
        if vfio_bound():
            return "vfio-pci bound (IOMMU passthrough active)"
        return "no device bound to vfio-pci"

    def prompts(self, profile: Profile) -> list[Prompt]:
        gpus = discover_gpus()
        choices = tuple(f"{bdf} {desc}" for bdf, desc in gpus) or ("(no GPU detected)",)
        return [
            Prompt(
                kind="confirm",
                question="Remove existing GPU PT/VFIO configs first?",
                default="n",
                id="vfio.revert",
            ),
            Prompt(
                kind="device",
                question="Select GPU to pass through",
                choices=choices,
                default=choices[0],
                id="vfio.gpu",
            ),
            Prompt(
                kind="confirm",
                question="Rebuild bootloader config after cmdline update?",
                default="y",
                id="vfio.rebuild_bootloader",
            ),
        ]

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []
        gpu = _selected_gpu(answers)
        if gpu is None:
            actions.append(
                Action(
                    key="vfio.no_gpu",
                    func=_no_gpu_error,
                    describe="no GPU detected; passthrough impossible",
                )
            )
            return actions

        bdf, _desc, vendor_id, device_ids = gpu
        ids_str = ",".join(device_ids)

        # 1. optional revert of previous config
        if answers.values.get("vfio.revert", "n").lower() in ("y", "yes", "true"):
            actions.append(
                Action(
                    key="vfio.revert",
                    func=_revert_vfio,
                    describe="remove vfio.conf + strip VFIO kernel opts from bootloader",
                )
            )

        # 2. vfio.conf write (probe-gated on content match)
        if not _vfio_conf_current(ids_str, vendor_id):
            actions.append(
                Action(
                    key="vfio.conf",
                    func=lambda ctx: _write_vfio_conf(ctx, ids_str, vendor_id),
                    describe=f"write {VFIO_CONF_PATH} (ids={ids_str})",
                )
            )

        # 3. bootloader cmdline (probe-gated: opts already present?)
        kernel_opts = _kernel_opts(ids_str, host)
        bootloader, config_path = detect_bootloader()
        if not _bootloader_has_opts(config_path, kernel_opts):
            actions.append(
                Action(
                    key="vfio.bootloader",
                    func=lambda ctx: _configure_bootloader(
                        ctx, bootloader, config_path, kernel_opts
                    ),
                    describe=f"add '{' '.join(kernel_opts)}' to {bootloader} cmdline",
                )
            )

        # 4. bootloader rebuild (GRUB/Limine only, and only when the
        #    cmdline changed)
        if (
            actions
            and any(a.key == "vfio.bootloader" for a in actions)
            and bootloader in ("grub", "limine")
            and answers.values.get("vfio.rebuild_bootloader", "y").lower() in ("y", "yes", "true")
        ):
            actions.append(
                Action(
                    key="vfio.bootloader_rebuild",
                    func=lambda ctx: _rebuild_bootloader(ctx, bootloader),
                    describe=f"rebuild {bootloader} configuration",
                )
            )

        return actions


# GPU discovery + IOMMU group validation (from vfio.sh configure_vfio).


def discover_gpus() -> list[tuple[str, str]]:
    """lspci class 0x03 devices -> [(bdf, description)].

    The bash flow: lspci -D lines whose /sys class file starts with
    0x03; desc is the bracketed subsystem text (##*[ ... %%]*).
    """
    import subprocess

    try:
        proc = subprocess.run(["lspci", "-D"], capture_output=True, text=True, check=False)
    except OSError:
        return []
    gpus: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        bdf = line.split(" ", 1)[0]
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d", bdf):
            continue
        if not _gpu_class_is_display(bdf):
            continue
        # desc = ${line##*[} ... ${desc%%]*}: the bracketed part
        if "[" in line:
            desc = line.split("[", 1)[1].split("]", 1)[0]
        else:
            desc = line.split(" ", 2)[-1]
        gpus.append((bdf, desc.strip()))
    return gpus


def _gpu_class_is_display(bdf: str, sys_root: Path = Path("/sys")) -> bool:
    class_file = sys_root / f"bus/pci/devices/{bdf}/class"
    try:
        return class_file.read_text().strip().startswith("0x03")
    except OSError:
        return False


def iommu_group_of(bdf: str, sys_root: Path = Path("/sys")) -> int | None:
    link = sys_root / f"bus/pci/devices/{bdf}/iommu_group"
    try:
        return int(link.resolve().name)
    except (OSError, ValueError):
        return None


def iommu_group_devices(group: int, sys_root: Path = Path("/sys")) -> list[str]:
    import os

    base = sys_root / f"kernel/iommu_groups/{group}/devices"
    try:
        return sorted(os.listdir(base))
    except OSError:
        return []


def validate_iommu_isolation(
    bdf: str, sys_root: Path = Path("/sys")
) -> tuple[bool, list[str], list[str]]:
    """(ok, ids, intruders): ids are vendor:device of the whole group;
    intruders are devices outside the target's slot prefix."""
    group = iommu_group_of(bdf, sys_root)
    if group is None:
        return False, [], []
    prefix = bdf.rsplit(".", 1)[0]
    ids: list[str] = []
    intruders: list[str] = []
    for dev in iommu_group_devices(group, sys_root):
        vendor = _read_sys(sys_root / f"bus/pci/devices/{dev}/vendor")
        device = _read_sys(sys_root / f"bus/pci/devices/{dev}/device")
        if vendor and device:
            ids.append(f"{vendor[2:]}:{device[2:]}")
        if not dev.startswith(f"{prefix}."):
            intruders.append(dev)
    return not intruders, ids, intruders


def _read_sys(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _selected_gpu(answers: PromptAnswers):
    """From the device prompt answer -> (bdf, desc, vendor_id, group_ids)."""
    raw = answers.values.get("vfio.gpu", "")
    if not raw:
        return None
    bdf = raw.split(" ", 1)[0]
    gpus = {b: d for b, d in discover_gpus()}
    if bdf not in gpus:
        return None
    ok, ids, intruders = validate_iommu_isolation(bdf)
    if not ok:
        raise RuntimeError(
            f"poor IOMMU grouping: intruders {intruders}; "
            "VFIO PT requires full group isolation (BIOS update, ACS "
            "override patch, or new motherboard)"
        )
    vendor = _read_sys(Path(f"/sys/bus/pci/devices/{bdf}/vendor")) or "0x0000"
    return bdf, gpus[bdf], vendor, ids


def _no_gpu_error(ctx: RunContext) -> None:
    raise RuntimeError("No GPUs detected! Passing through would leave the host headless.")


# vfio.conf + bootloader cmdline (pure text transforms + root writes).


def vfio_conf_content(ids: str, vendor_id: str) -> str:
    drivers = GPU_DRIVERS.get(vendor_id, "")
    lines = [f"options vfio-pci ids={ids} disable_vga=1"]
    if drivers:
        lines.append(f"softdep {drivers} pre: vfio-pci")
    return "\n".join(lines) + "\n"


def _vfio_conf_current(ids: str, vendor_id: str) -> bool:
    """Semantic check: the ids= line matches. Softdep lines may be
    split per-driver, which is equivalent; the live host has it."""
    try:
        current = VFIO_CONF_PATH.read_text()
    except OSError:
        return False
    wanted = f"options vfio-pci ids={ids} disable_vga=1"
    return wanted in current


def _bootloader_has_opts(config_path: str, kernel_opts: list[str]) -> bool:
    """True when every kernel opt is already on the cmdline (bash: the
    grep that skips append when vfio-pci.ids already present)."""
    try:
        text = Path(config_path).read_text()
    except OSError:
        return False
    return all(opt in text for opt in kernel_opts)


def _write_vfio_conf(ctx: RunContext, ids: str, vendor_id: str) -> None:
    content = vfio_conf_content(ids, vendor_id)
    _write_root_file(ctx, VFIO_CONF_PATH, content)
    ctx.log(f"wrote {VFIO_CONF_PATH}")


def _kernel_opts(ids: str, host: Host) -> list[str]:
    opts = ["iommu=pt", f"vfio-pci.ids={ids}"]
    if host.cpu_vendor == "GenuineIntel":
        opts = ["intel_iommu=on", *opts]
    return opts


def strip_vfio_opts(line: str) -> str:
    """Remove VFIO kernel opts from one cmdline, collapsing spaces."""
    cleaned = VFIO_KERNEL_OPTS_REGEX.sub("", line)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def grub_line_new_value(current: str, kernel_opts: list[str]) -> str:
    """GRUB_CMDLINE_LINUX_DEFAULT=... with VFIO opts (re)appended."""
    inner = current.split("=", 1)[1] if "=" in current else current
    inner = inner.strip('"')
    cleaned = strip_vfio_opts(inner)
    joined = (cleaned + " " + " ".join(kernel_opts)).strip()
    return f'GRUB_CMDLINE_LINUX_DEFAULT="{joined}"'


def detect_bootloader() -> tuple[str, str]:
    """Return (type, config_path), in the vfio.sh detect_bootloader order."""
    if Path("/etc/default/limine").is_file():
        return "limine", "/etc/default/limine"
    if Path("/etc/default/grub").is_file():
        return "grub", "/etc/default/grub"
    for directory in SDBOOT_CONF_LOCATIONS:
        directory_path = Path(directory)
        if not directory_path.is_dir():
            continue
        entries = sorted(p for p in directory_path.glob("*.conf") if "fallback" not in p.name)
        if entries:
            return "systemd-boot", str(entries[0])
        if Path("/etc/kernel/cmdline").is_file() and any(Path("/boot/EFI/Linux").glob("*.efi")):
            return "systemd-boot", "/etc/kernel/cmdline"
    return "unknown", ""


def _configure_bootloader(
    ctx: RunContext, bootloader: str, config_path: str, kernel_opts: list[str]
) -> None:
    text = Path(config_path).read_text()
    opts_str = " ".join(kernel_opts)

    if bootloader == "grub":
        new_text = _edit_grub(text, kernel_opts)
    elif bootloader == "systemd-boot" and config_path == "/etc/kernel/cmdline":
        new_text = _edit_uki(text, kernel_opts)
    elif bootloader == "systemd-boot":
        new_text = _edit_sdboot_entry(text, kernel_opts)
    elif bootloader == "limine":
        new_text = _edit_limine(text, kernel_opts)
    else:
        raise RuntimeError(f"no supported bootloader detected (got {bootloader!r})")

    _write_root_file(ctx, Path(config_path), new_text)
    ctx.log(f"updated {bootloader} cmdline in {config_path}: + {opts_str}")


def _edit_grub(text: str, kernel_opts: list[str]) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("GRUB_CMDLINE_LINUX_DEFAULT="):
            lines.append(grub_line_new_value(line, kernel_opts))
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _edit_uki(text: str, kernel_opts: list[str]) -> str:
    cleaned = strip_vfio_opts(text)
    return cleaned + " " + " ".join(kernel_opts) + "\n"


def _edit_sdboot_entry(text: str, kernel_opts: list[str]) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("options "):
            cleaned = strip_vfio_opts(line[len("options ") :])
            lines.append("options " + " ".join([cleaned] + list(kernel_opts)).strip())
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _edit_limine(text: str, kernel_opts: list[str]) -> str:
    lines = []
    for line in text.splitlines():
        if LIMINE_ENTRY_REGEX.match(line):
            cleaned = strip_vfio_opts(line)
            if cleaned.endswith('"'):
                lines.append(cleaned[:-1] + " " + " ".join(kernel_opts) + '"')
            else:
                lines.append(cleaned + " " + " ".join(kernel_opts))
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _revert_vfio(ctx: RunContext) -> None:
    bootloader, config_path = detect_bootloader()
    if VFIO_CONF_PATH.is_file():
        ctx.sh(["rm", "-v", str(VFIO_CONF_PATH)], root=True)
        ctx.log(f"removed {VFIO_CONF_PATH}")

    if config_path:
        text = Path(config_path).read_text()
        new_text = _strip_all_bootloader(text, bootloader)
        if new_text != text:
            _write_root_file(ctx, Path(config_path), new_text)
            ctx.log(f"stripped VFIO kernel opts from {config_path}")


def _strip_all_bootloader(text: str, bootloader: str) -> str:
    lines = []
    for line in text.splitlines():
        if bootloader == "grub" and line.startswith("GRUB_CMDLINE_LINUX_DEFAULT="):
            inner = line.split("=", 1)[1].strip('"')
            lines.append(f'GRUB_CMDLINE_LINUX_DEFAULT="{strip_vfio_opts(inner)}"')
        elif bootloader == "systemd-boot" and line.startswith("options "):
            lines.append("options " + strip_vfio_opts(line[len("options ") :]))
        elif bootloader == "systemd-boot" and line == text.strip() and "options" not in text:
            lines.append(strip_vfio_opts(line))
        elif bootloader == "limine" and LIMINE_ENTRY_REGEX.match(line):
            lines.append(strip_vfio_opts(line))
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _rebuild_bootloader(ctx: RunContext, bootloader: str) -> None:
    if bootloader == "grub":
        for cmd in ("grub-mkconfig", "grub2-mkconfig"):
            if _command_exists(ctx, cmd):
                cfg = f"/boot/{cmd.replace('-mkconfig', '')}/grub.cfg"
                ctx.sh([cmd, "-o", cfg], root=True)
                ctx.log(f"bootloader configuration updated ({cmd})")
                return
        raise RuntimeError("no known GRUB configuration command found")
    if bootloader == "limine":
        if _command_exists(ctx, "limine-mkinitcpio"):
            ctx.sh(["limine-mkinitcpio"], root=True)
            ctx.log("bootloader configuration updated (limine-mkinitcpio)")
            return
        raise RuntimeError("limine-mkinitcpio command not found")
    raise RuntimeError(f"no rebuild needed for {bootloader}")


def _command_exists(ctx: RunContext, name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def _write_root_file(ctx: RunContext, path: Path, content: str) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    try:
        ctx.sh(["cp", str(tmp), str(path)], root=True)
    finally:
        tmp.unlink(missing_ok=True)
