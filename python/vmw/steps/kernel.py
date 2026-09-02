"""kernel step: patched linux-tkg build.

Probes: /boot vmlinuz-<tag> or HvP-RDTSC.conf boot entry.
The kernel patch and all patch content are never modified by this
module.

Cancellation hygiene [A5]: the plan starts with an always-run reset
action (git checkout -- . && git clean) so a cancelled build is
cleaned by the next rebuild.

The customization.cfg renderer produces byte-identical output to the
bash sed path; test_kernel_customization validates that against the
file the bash flow wrote on this machine (plan 02 VALIDATION).
"""

from __future__ import annotations

import re
from pathlib import Path

from vmw.infra.host import Host
from vmw.infra.probe import State, kernel_boot_entry_present
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import Prompt, PromptAnswers
from vmw.workflow.step import Step

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
TKG_DIR = "linux-tkg"
TKG_URI = "https://github.com/Frogging-Family/linux-tkg.git"

KERNEL_MAJOR = "7"
KERNEL_MINOR = "0"
KERNEL_PATCH = "latest"
KERNEL_VERSION = f"{KERNEL_MAJOR}.{KERNEL_MINOR}-{KERNEL_PATCH}"
KERNEL_TAG = f"linux{KERNEL_MAJOR}{KERNEL_MINOR}-tkg-eevdf"
BOOT_TAG_FALLBACK = KERNEL_TAG

REQUIRED_DISK_SPACE_GB = 35

# linux-tkg userpatch filename per CPU vendor. Named by kernel version
# (7.0.2), not the {vendor}-{tag} shape edk2/qemu use, so it needs its own
# map rather than the f-string default those steps build.
KERNEL_PATCH_BY_VENDOR: dict[str, str] = {
    "AMD": "amd702.mypatch",
    "Intel": "intel702.mypatch",
}

# bash kernel.sh detect_and_select_cpu() architecture lists.
CPU_OPT_ARCHITECTURES: dict[str, list[str]] = {
    "AMD": [
        "k8",
        "k8sse3",
        "k10",
        "barcelona",
        "bobcat",
        "jaguar",
        "bulldozer",
        "piledriver",
        "steamroller",
        "excavator",
        "znver1",
        "znver2",
        "znver3",
        "znver4",
        "znver5",
        "native_amd",
    ],
    "Intel": [
        "mpsc",
        "atom",
        "core2",
        "nehalem",
        "westmere",
        "silvermont",
        "sandybridge",
        "ivybridge",
        "haswell",
        "broadwell",
        "skylake",
        "skylakex",
        "cannonlake",
        "icelake",
        "icelake_server",
        "goldmont",
        "goldmontplus",
        "cascadelake",
        "cooperlake",
        "tigerlake",
        "sapphirerapids",
        "rocketlake",
        "alderlake",
        "raptorlake",
        "meteorlake",
        "native_intel",
    ],
}

# bash kernel.sh select_distro() options.
TKG_DISTROS = ("Arch", "Ubuntu", "Debian", "Fedora", "Suse", "Gentoo", "Generic")

# customization.cfg keys the bash apply_tkg_config() sed sets.
CUSTOMIZATION_KEYS = (
    "_distro",
    "_version",
    "_EXT_CONFIG_PATH",
    "_menunconfig",
    "_diffconfig",
    "_cpusched",
    "_compiler",
    "_sched_yield_type",
    "_rr_interval",
    "_tickless",
    "_acs_override",
    "_processor_opt",
    "_timer_freq",
    "_user_patches_no_confirm",
    "_force_all_threads",
    "_modprobeddb",
)


class KernelStep(Step):
    name = "kernel"
    title = "Build patched kernel (linux-tkg)"

    def probe(self, host: Host) -> State:
        tag = self.kernel_tag()
        if kernel_boot_entry_present(tag):
            return State.DONE
        return State.MISSING

    def probe_detail(self, host: Host) -> str:
        tag = self.kernel_tag()
        if kernel_boot_entry_present(tag):
            return f"boot entry for {tag} present"
        return f"no boot entry for {tag}"

    @staticmethod
    def kernel_tag() -> str:
        """linux<major><minor>-tkg-eevdf. Matches the tkg _version that
        the build installs and that this step's probe looks for in
        /boot."""
        return KERNEL_TAG

    def prompts(self, profile: Profile) -> list[Prompt]:
        host_manufacturer = _detect_cpu_manufacturer()
        archs = CPU_OPT_ARCHITECTURES.get(host_manufacturer, ["generic"])
        return [
            Prompt(
                kind="choice",
                question=f"Select tkg distro target (host is {host_manufacturer})",
                choices=TKG_DISTROS,
                default="Arch",
                id="kernel.distro",
            ),
            Prompt(
                kind="choice",
                question=f"Select CPU microarchitecture ({host_manufacturer})",
                choices=archs,
                default=archs[-1],
                id="kernel.cpu_opt",
            ),
            Prompt(
                kind="confirm",
                question="Enable ACS override patch (for IOMMU groups)?",
                default="y",
                id="kernel.acs_override",
            ),
        ]

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []

        # 0. reset-first [A5]: a cancelled build is cleaned by the next
        # run. Restore tracked files to HEAD first; git clean alone
        # leaves a previous patch applied in tracked files.
        if _tkg_clone_exists():
            actions.append(
                Action(
                    key="kernel.reset",
                    cmd=["sh", "-c", "git restore --worktree :/ && git clean -fd"],
                    cwd=str(SRC_DIR / TKG_DIR),
                    describe="reset linux-tkg tree to pristine HEAD (cancel hygiene [A5])",
                    always=True,
                )
            )

        # 1. acquire source
        if not _tkg_clone_exists():
            actions.append(
                Action(
                    key="kernel.clone",
                    cmd=["git", "clone", "--depth=1", TKG_URI, TKG_DIR],
                    cwd=str(SRC_DIR),
                    describe=f"clone linux-tkg from {TKG_URI}",
                )
            )
            actions.append(
                Action(
                    key="kernel.strip_werror",
                    func=_strip_werror,
                    describe="strip -Werror from tkg scripts (newer compilers)",
                )
            )

        # 2. disk space check
        actions.append(
            Action(
                key="kernel.check_space",
                func=_check_disk_space,
                describe=f"require {REQUIRED_DISK_SPACE_GB}GB free for the build",
            )
        )

        # 3. customization.cfg
        distro = answers.values.get("kernel.distro", "Arch")
        cpu_opt = answers.values.get("kernel.cpu_opt") or _default_cpu_opt()
        acs_override = answers.values.get("kernel.acs_override", "y").lower() in (
            "y",
            "yes",
            "true",
        )
        actions.append(
            Action(
                key="kernel.customization",
                func=lambda ctx: _write_customization(ctx, distro, cpu_opt, acs_override),
                describe=(
                    f"write customization.cfg "
                    f"(distro={distro}, cpu_opt={cpu_opt}, acs={acs_override})"
                ),
            )
        )

        # 4. stage the kernel patch
        patch_name = _kernel_patch_name(profile, host)
        actions.append(
            Action(
                key="kernel.stage_patch",
                func=lambda ctx: _stage_patch(ctx, patch_name),
                describe=(
                    f"stage {patch_name} into linux{KERNEL_MAJOR}{KERNEL_MINOR}-tkg-userpatches/"
                ),
            )
        )

        # 4b. patch drift check (kernel.sh patch_kernel_files)
        actions.append(
            Action(
                key="kernel.patch_drift",
                func=lambda ctx: _check_patch_drift(ctx, patch_name),
                describe=f"verify {patch_name} targets {KERNEL_VERSION}",
            )
        )

        # 5. build
        if distro == "Arch":
            actions.append(
                Action(
                    key="kernel.makepkg",
                    cmd=["makepkg", "-C", "-si", "--noconfirm"],
                    cwd=str(SRC_DIR / TKG_DIR),
                    describe="build + install the kernel package (makepkg)",
                    terminal=True,  # makepkg -si runs its own sudo on /dev/tty [A2]
                )
            )
        else:
            actions.append(
                Action(
                    key="kernel.install_sh",
                    cmd=["./install.sh", "install"],
                    cwd=str(SRC_DIR / TKG_DIR),
                    describe="build + install the kernel (tkg install.sh)",
                    terminal=True,
                )
            )

        # 6. boot entries
        actions.append(
            Action(
                key="kernel.boot_entry",
                func=_write_boot_entries,
                describe="write HvP-RDTSC systemd-boot / GRUB entries (root)",
                root=True,
            )
        )

        return actions


def _detect_cpu_manufacturer() -> str:
    try:
        from vmw.infra.host import detect_cpu

        return detect_cpu()[1]
    except Exception:
        return "generic"


def _default_cpu_opt() -> str:
    archs = CPU_OPT_ARCHITECTURES.get(_detect_cpu_manufacturer(), ["generic"])
    return archs[-1]


def _tkg_clone_exists() -> bool:
    return (SRC_DIR / TKG_DIR / "install.sh").is_file()


def render_customization(
    distro: str,
    version: str = KERNEL_VERSION,
    cpu_opt: str = "znver3",
    acs_override: bool = True,
    cpusched: str = "eevdf",
    tickless: str = "1",
    timer_freq: str = "1000",
) -> dict[str, str]:
    """The customization.cfg key/values the bash sed path sets."""
    return {
        "_distro": distro,
        "_version": version,
        "_EXT_CONFIG_PATH": "",
        "_menunconfig": "false",
        "_diffconfig": "false",
        "_cpusched": cpusched,
        "_compiler": "gcc",
        "_sched_yield_type": "0",
        "_rr_interval": "2",
        "_tickless": tickless,
        "_acs_override": "true" if acs_override else "false",
        "_processor_opt": cpu_opt,
        "_timer_freq": timer_freq,
        "_user_patches_no_confirm": "true",
        "_force_all_threads": "true",
        "_modprobeddb": "false",
    }


CUSTOMIZATION_SED_RE = re.compile(r"^(_[a-zA-Z0-9_]+)=.*$")


def apply_customization_to_text(cfg_text: str, values: dict[str, str]) -> str:
    """Replace key= lines exactly like the bash sed s|^key=.*|key="value"|.

    Byte-parity: each replacement writes key="value", quoted like
    bash, and the iteration order follows CUSTOMIZATION_KEYS.
    """
    out_lines: list[str] = []
    for line in cfg_text.splitlines(keepends=False):
        m = CUSTOMIZATION_SED_RE.match(line)
        if m and m.group(1) in values:
            key = m.group(1)
            out_lines.append(f'{key}="{values[key]}"')
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


def _write_customization(ctx: RunContext, distro: str, cpu_opt: str, acs_override: bool) -> None:
    cfg_path = SRC_DIR / TKG_DIR / "customization.cfg"
    values = render_customization(distro=distro, cpu_opt=cpu_opt, acs_override=acs_override)
    text = cfg_path.read_text()
    new_text = apply_customization_to_text(text, values)
    cfg_path.write_text(new_text)
    ctx.log(f"wrote customization.cfg (distro={distro}, cpu={cpu_opt})")


def _strip_werror(ctx: RunContext) -> None:
    r"""grep -RIl '\-Werror' . | xargs -r sed -i 's/-Werror=/-W/g; ...'"""
    clone = SRC_DIR / TKG_DIR
    count = 0
    for path in clone.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(errors="surrogateescape")
        except OSError:
            continue
        if "-Werror" not in text:
            continue
        new_text = text.replace("-Werror=", "-W").replace("-Werror-", "-W").replace("-Werror", "-W")
        with path.open("w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            handle.write(new_text)
        count += 1
    ctx.log(f"stripped -Werror from {count} files")


def _check_disk_space(ctx: RunContext) -> None:
    import shutil

    free_gb = shutil.disk_usage(str(SRC_DIR)).free // (1024**3)
    if free_gb < REQUIRED_DISK_SPACE_GB:
        raise RuntimeError(
            f"insufficient disk space on {SRC_DIR}: {free_gb}GB free, "
            f"{REQUIRED_DISK_SPACE_GB}GB required"
        )
    ctx.log(f"disk space check passed ({free_gb}GB free)")


def _kernel_patch_name(profile: Profile, host: Host) -> str:
    """Profile's configured patch, else the patch for the running Host.

    Uses the Host handed to plan() rather than re-detecting the CPU, so the
    kernel step targets the same machine as edk2/qemu. An unmapped vendor
    yields "" and the stage step skips patching.
    """
    from vmw.steps.patchsel import select_patch

    host_default = KERNEL_PATCH_BY_VENDOR.get(host.cpu_manufacturer, "")
    return select_patch("Kernel", profile.patches.kernel, host_default)


def _stage_patch(ctx: RunContext, patch_name: str) -> None:
    if not patch_name:
        ctx.log("no kernel patch configured; skipping staging")
        return
    source = REPO_ROOT / "patches" / "Kernel" / patch_name
    if not source.is_file():
        raise RuntimeError(f"kernel patch not found: {source}")
    user_patch_dir = SRC_DIR / TKG_DIR / f"linux{KERNEL_MAJOR}{KERNEL_MINOR}-tkg-userpatches"
    user_patch_dir.mkdir(parents=True, exist_ok=True)
    target = user_patch_dir / patch_name
    target.write_bytes(source.read_bytes())
    ctx.log(f"staged {patch_name} -> {user_patch_dir.name}/")


def _check_patch_drift(ctx: RunContext, patch_name: str) -> None:
    """kernel.sh patch_kernel_files(): warn + confirm on version drift."""
    if not patch_name:
        return
    from vmw.patches import target_version

    patch_path = REPO_ROOT / "patches" / "Kernel" / patch_name
    stamped = target_version(str(patch_path))
    if not stamped:
        return
    kernel_ver = f"{KERNEL_MAJOR}{KERNEL_MINOR}"
    if stamped not in kernel_ver and kernel_ver not in stamped:
        # bash asks "Continue anyway?". The plan flow answers via the
        # confirm prompt; the run flow raises so the engine reports it.
        raise RuntimeError(
            f"kernel patch '{patch_name}' targets {stamped} but kernel source is "
            f"{KERNEL_VERSION} - drift detected"
        )
    ctx.log(f"patch {patch_name} version stamp OK ({stamped})")


# Boot entries (kernel.sh create_systemd_boot_entry / create_grub_entry).
BOOT_ENTRY_DIRS = (
    "/boot/loader/entries",
    "/boot/efi/loader/entries",
    "/efi/loader/entries",
)

ENTRY_NAME = "HvP-RDTSC"


def _write_boot_entries(ctx: RunContext) -> None:
    entry_dir = next((d for d in BOOT_ENTRY_DIRS if Path(d).is_dir()), "")
    if entry_dir:
        _write_systemd_boot_entry(ctx, entry_dir)
    else:
        _write_grub_entry(ctx)


def _root_options(ctx: RunContext) -> str:
    """root=PARTUUID=<uuid> rw rootfstype=<fstype> via findmnt/blkid."""
    root_dev = ctx.sh(["findmnt", "-n", "-o", "SOURCE", "/"], root=True)
    partuuid = ctx.sh(["blkid", "-s", "PARTUUID", "-o", "value", root_dev.split("[")[0]], root=True)
    fstype = ctx.sh(["findmnt", "-n", "-o", "FSTYPE", "/"], root=True)
    return f"root=PARTUUID={partuuid} rw rootfstype={fstype}"


def _write_systemd_boot_entry(ctx: RunContext, entry_dir: str) -> None:
    import datetime

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    options = _root_options(ctx)

    main = (
        f"# Created by: HvP-Script ({timestamp})\n"
        f"title   HvP (RDTSC Patch)\n"
        f"linux   /vmlinuz-{KERNEL_TAG}\n"
        f"initrd  /initramfs-{KERNEL_TAG}.img\n"
        f"{options}\n"
    )
    fallback = (
        f"# Created by: HvP-Script ({timestamp})\n"
        f"title   HvP (RDTSC Patch - Fallback)\n"
        f"linux   /vmlinuz-{KERNEL_TAG}\n"
        f"initrd  /initramfs-{KERNEL_TAG}-fallback.img\n"
        f"{options}\n"
    )
    for name, content in (
        (f"{ENTRY_NAME}.conf", main),
        (f"{ENTRY_NAME}-fallback.conf", fallback),
    ):
        _write_root_file(ctx, Path(entry_dir) / name, content)
    ctx.log(f"wrote {ENTRY_NAME} systemd-boot entries to {entry_dir}")


def _write_grub_entry(ctx: RunContext) -> None:
    options = _root_options(ctx)
    entry = (
        "\n# Added by VMW: patched research kernel\n"
        'menuentry "HvP-RDTSC (linux-tkg eevdf)" --class kernel --class os {\n'
        "    load_video\n"
        "    set gfxpayload=keep\n"
        "    insmod gzio\n"
        "    insmod part_gpt\n"
        "    insmod ext2\n"
        f"    echo 'Loading Linux {KERNEL_TAG} ...'\n"
        f"    linux /vmlinuz-{KERNEL_TAG} {options}\n"
        "    echo 'Loading initial ramdisk ...'\n"
        f"    initrd /initramfs-{KERNEL_TAG}.img\n"
        "}\n"
    )
    _append_root_file(ctx, Path("/etc/grub.d/40_custom"), entry)
    ctx.sh(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], root=True)
    ctx.log("GRUB entry appended and grub.cfg regenerated")


def _write_root_file(ctx: RunContext, path: Path, content: str) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    try:
        ctx.sh(["cp", str(tmp), str(path)], root=True)
        ctx.sh(["chmod", "0644", str(path)], root=True)
    finally:
        tmp.unlink(missing_ok=True)


def _append_root_file(ctx: RunContext, path: Path, content: str) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    try:
        ctx.sh(["sh", "-c", f"cat '{tmp}' >> '{path}'"], root=True)
    finally:
        tmp.unlink(missing_ok=True)
