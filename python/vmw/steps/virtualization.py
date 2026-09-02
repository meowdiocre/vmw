"""virtualization step: libvirt stack + vmw-Router (from modules/virtualization.sh).

Every bash side effect becomes a probe-gated action: package install,
user groups, qemu.conf user/group, libvirtd enable, the vmw-Router
net-define heredoc, the VMM gsettings toggle. The MAC-from-ARP
derivation is ported as a pure helper.
"""

from __future__ import annotations

from pathlib import Path

from vmw.infra.host import Host
from vmw.infra.packages import install_command, missing, packages_for
from vmw.infra.probe import State, libvirt_network_present, libvirtd_active
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import PromptAnswers
from vmw.workflow.step import Step

QEMU_CONF = "/etc/libvirt/qemu.conf"
REQUIRED_GROUPS = ("input", "kvm", "libvirt")
VMW_ROUTER_NETWORK = "vmw-Router"


class VirtualizationStep(Step):
    name = "virtualization"
    title = "Install virtualization stack (libvirt, QEMU, swtpm)"

    def probe(self, host: Host) -> State:
        if libvirtd_active() and libvirt_network_present():
            return State.DONE
        if libvirtd_active() or libvirt_network_present():
            return State.PARTIAL
        return State.MISSING

    def probe_detail(self, host: Host) -> str:
        parts = []
        parts.append("libvirtd up" if libvirtd_active() else "libvirtd down")
        parts.append("vmw-Router defined" if libvirt_network_present() else "vmw-Router missing")
        return ", ".join(parts)

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []
        target_user = _default_user()

        # 1. packages
        pkgs = packages_for(host.distro, "virtualization")
        need = missing(pkgs, host.distro)
        if need:
            actions.append(
                Action(
                    key="virtualization.packages",
                    cmd=install_command(host.distro, need),
                    root=True,
                    describe=f"install {', '.join(need)}",
                )
            )

        # 2. user groups
        for grp in REQUIRED_GROUPS:
            if not _user_has_group(target_user, grp):
                actions.append(
                    Action(
                        key=f"virtualization.group.{grp}",
                        cmd=["usermod", "-aG", grp, target_user],
                        root=True,
                        describe=f"add {target_user} to {grp}",
                    )
                )

        # 3. qemu.conf user/group
        if not _qemu_conf_done(target_user, QEMU_CONF):
            actions.append(
                Action(
                    key="virtualization.qemu_conf",
                    cmd=[
                        "sed",
                        "-i",
                        "-E",
                        f's/^#(user|group) = \\".*\\"/\\1 = \\"{target_user}\\"/',
                        QEMU_CONF,
                    ],
                    root=True,
                    describe=f"set user/group = {target_user} in qemu.conf",
                )
            )

        # 4. libvirtd service
        if not libvirtd_active():
            actions.append(
                Action(
                    key="virtualization.libvirtd",
                    cmd=["systemctl", "enable", "--now", "libvirtd"],
                    root=True,
                    describe="enable and start libvirtd",
                )
            )

        # 5. vmw-Router network
        if not libvirt_network_present():
            mac = _hybrid_mac(arp_table=_read_arp())
            actions.append(
                Action(
                    key="virtualization.network",
                    func=_define_network,
                    describe=f"define + autostart + start vmw-Router (mac {mac})",
                )
            )

        # 6. VMM XML editor gsetting
        if not _vmm_xmleditor_enabled():
            actions.append(
                Action(
                    key="virtualization.vmm_xmleditor",
                    cmd=[
                        "gsettings",
                        "set",
                        "org.virt-manager.virt-manager",
                        "xmleditor-enabled",
                        "true",
                    ],
                    describe="enable VMM XML editor",
                )
            )

        return actions


def _define_network(ctx: RunContext) -> None:
    mac = _hybrid_mac(arp_table=_read_arp())
    xml = VMW_ROUTER_XML.format(mac=mac)
    # virsh net-define reads a file; feed via temp file to avoid argv-borne stdin
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
        handle.write(xml)
        path = handle.name
    try:
        ctx.sh(["virsh", "--connect", "qemu:///system", "net-define", path], root=True)
        ctx.sh(
            ["virsh", "--connect", "qemu:///system", "net-autostart", VMW_ROUTER_NETWORK], root=True
        )
        ctx.sh(["virsh", "--connect", "qemu:///system", "net-start", VMW_ROUTER_NETWORK], root=True)
    finally:
        import os

        os.unlink(path)


VMW_ROUTER_XML = """<network>
  <name>vmw-Router</name>
  <forward mode="nat"/>
  <mac address="{mac}"/>
  <ip address="10.0.0.1" netmask="255.255.255.0">
    <dhcp>
      <range start="10.0.0.2" end="10.0.0.254"/>
    </dhcp>
  </ip>
</network>
"""


def _hybrid_mac(arp_table: str, random_source=None) -> str:
    """OUI of the default gateway + 3 random bytes (bash line 62)."""
    gateway = _default_gateway()
    if not gateway:
        return ""
    for line in arp_table.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == gateway:
            router_mac = fields[3]
            oui = ":".join(router_mac.split(":")[:3])
            tail = ":".join(f"{b:02x}" for b in _three_bytes(random_source))
            return f"{oui}:{tail}"
    return ""


def _three_bytes(random_source=None) -> tuple[int, int, int]:
    import random

    rng = random_source or random
    return rng.randrange(256), rng.randrange(256), rng.randrange(256)


def _default_gateway() -> str:
    try:
        import subprocess

        proc = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, check=False
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if "default" in line:
                    parts = line.split()
                    if "via" in parts:
                        return parts[parts.index("via") + 1]
    except (OSError, ValueError):
        pass
    return ""


def _read_arp() -> str:
    try:
        return Path("/proc/net/arp").read_text()
    except OSError:
        return ""


def _user_has_group(user: str, group: str, run=None) -> bool:
    capture = run or run_capture_groups
    out = capture(user)
    if not out:
        return False
    return f" {group} " in f" {out.strip()} "


def run_capture_groups(user: str) -> str:
    import subprocess

    try:
        proc = subprocess.run(["id", "-nG", user], capture_output=True, text=True, check=False)
        return proc.stdout
    except OSError:
        return ""


def _qemu_conf_done(user: str, conf_path: str) -> bool:
    from pathlib import Path

    try:
        text = Path(conf_path).read_text()
    except OSError:
        return False
    return f'user = "{user}"' in text or f'group = "{user}"' in text


def _vmm_xmleditor_enabled() -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["gsettings", "get", "org.virt-manager.virt-manager", "xmleditor-enabled"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0 and "true" in proc.stdout


def _default_user() -> str:
    import os

    return os.environ.get("SUDO_USER") or os.environ.get("USER") or ""
