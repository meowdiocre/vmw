"""Domain facts the host can read for the right-pane detail (plan 07).

Everything here comes from `virsh dumpxml` or the profile itself, so no
value can drift from reality the way a copied number would. When the
domain is not defined we fall back to the profile's intended shape,
tagged so the UI can say "not yet deployed".
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainFacts:
    name: str
    defined: bool  # False => values are the profile's intent, not a live domain
    disk_bus: str
    disk_size: str
    mac: str
    network: str
    gpu: str
    tpm: str
    hvci: str
    firmware: str

    @property
    def source_label(self) -> str:
        return "live domain" if self.defined else "profile (not deployed)"


def parse_dumpxml(name: str, xml: str) -> DomainFacts:
    """Pull the facts we display out of a `virsh dumpxml` document."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return _unknown(name, defined=True)

    disk_bus = "-"
    for disk in root.iter("disk"):
        if disk.get("device") != "disk":
            continue
        target = disk.find("target")
        if target is not None:
            disk_bus = target.get("bus", "-")
        break

    mac = "-"
    network = "-"
    for iface in root.iter("interface"):
        mac_el = iface.find("mac")
        if mac_el is not None:
            mac = mac_el.get("address", "-")
        src = iface.find("source")
        if src is not None:
            network = src.get("network") or src.get("bridge") or "-"
        break

    gpu = "none"
    for hostdev in root.iter("hostdev"):
        if hostdev.get("type") == "pci":
            gpu = "pci passthrough"
            break

    tpm = "none"
    tpm_el = root.find(".//tpm")
    if tpm_el is not None:
        backend = tpm_el.find("backend")
        version = backend.get("version", "") if backend is not None else ""
        tpm = f"{tpm_el.get('model', 'tpm')} {version}".strip()

    firmware = "-"
    loader = root.find(".//loader")
    if loader is not None and loader.text:
        firmware = loader.text.split("/")[-1]

    return DomainFacts(
        name=name,
        defined=True,
        disk_bus=disk_bus,
        disk_size="-",  # not in dumpxml without a storage query
        mac=mac,
        network=network,
        gpu=gpu,
        tpm=tpm,
        hvci="see guest",  # HVCI is a guest setting; host XML cannot show it
        firmware=firmware,
    )


def facts_from_profile(profile) -> DomainFacts:
    """The intended shape of a domain that is not yet defined."""
    dev = profile.device
    return DomainFacts(
        name=profile.domain_name,
        defined=False,
        disk_bus=getattr(dev, "disk_bus", "-"),
        disk_size=f"{getattr(dev, 'disk_size_gb', '-')}G",
        mac="assigned at deploy",
        network="vmw-Router",
        gpu="pci passthrough" if _profile_has_gpu(profile) else "none",
        tpm=f"{getattr(dev, 'tpm_model', 'tpm')} 2.0"
        if getattr(dev, "tpm", "none") != "none"
        else "none",
        hvci="on" if profile.features.hyperv else "off",
        firmware=str(getattr(profile.boot, "loader", "-")).split("/")[-1],
    )


def _profile_has_gpu(profile) -> bool:
    passthrough = getattr(profile, "passthrough", None)
    return bool(passthrough and getattr(passthrough, "gpu", None))


def _unknown(name: str, defined: bool) -> DomainFacts:
    return DomainFacts(
        name=name,
        defined=defined,
        disk_bus="-",
        disk_size="-",
        mac="-",
        network="-",
        gpu="-",
        tpm="-",
        hvci="-",
        firmware="-",
    )


def read_domain_facts(
    name: str,
    profile=None,
    virsh: str = "virsh",
    run: callable = subprocess.run,
    which: callable = shutil.which,
) -> DomainFacts:
    """Live facts if the domain is defined, else the profile's intent.

    Never raises; degrades to the profile or to unknowns.
    """
    if which(virsh) is not None:
        try:
            proc = run(
                [virsh, "--connect", "qemu:///system", "dumpxml", name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return parse_dumpxml(name, proc.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    if profile is not None:
        return facts_from_profile(profile)
    return _unknown(name, defined=False)
