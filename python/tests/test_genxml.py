"""build_domain_xml(Profile) unit tests.

Covers the typed emitter against the two real profiles plus synthetic
profiles exercising disk/cdrom branching, GPU passthrough, acpitable
args, and the qemu:commandline assembly.
"""

from __future__ import annotations

import pytest
from lxml import etree
from vmw.genxml import build_domain_xml, to_string
from vmw.genxml.qemu_args import qemu_commandline_args
from vmw.profiles.loader import load_config

QEMU_NS = "http://libvirt.org/schemas/domain/qemu/1.0"


def _el(root, path):
    found = root.findall(path)
    assert found, f"missing element {path}"
    return found[0]


def _args(root):
    """qemu:commandline arg values as a flat list."""
    return [el.get("value") for el in root.findall(f"{{{QEMU_NS}}}commandline/{{{QEMU_NS}}}arg")]


# -- real profiles ---------------------------------------------------------


def test_example_core_elements():
    root = build_domain_xml(load_config("example"))
    assert root.get("type") == "kvm"
    assert _el(root, "name").text == "example"
    assert _el(root, "memory").text == str(8192 * 1024)
    assert _el(root, "vcpu").text == "8"
    # disk present with blockio + nvme target
    disk = _el(root, "devices/disk")
    assert disk.get("device") == "disk"
    assert _el(disk, "target").get("bus") == "nvme"
    assert _el(disk, "blockio").get("logical_block_size") == "4096"
    # cdrom from iso_path -> sdb (disk present)
    cdrom = root.findall("devices/disk")[1]
    assert cdrom.get("device") == "cdrom"
    assert _el(cdrom, "target").get("dev") == "sdb"


def test_example_commandline_machine_and_smbios():
    root = build_domain_xml(load_config("example"))
    args = _args(root)
    assert "-machine" in args
    machine = args[args.index("-machine") + 1]
    assert machine.startswith("pc-q35-11.0")
    assert "usb=off" in machine and "smm=on" in machine
    assert "-smbios" in args
    assert args[args.index("-smbios") + 1] == "file=/opt/vmw/firmware/smbios.bin"


def test_vmud_cdrom_only_until_disk():
    # vmud has no disk_path -> no boot disk, cdrom takes sda.
    root = build_domain_xml(load_config("vmud"))
    disks = root.findall("devices/disk")
    assert len(disks) == 1
    assert disks[0].get("device") == "cdrom"
    assert _el(disks[0], "target").get("dev") == "sda"


def test_hyperv_kvm_features():
    root = build_domain_xml(load_config("example"))
    feats = _el(root, "features")
    hyperv = _el(feats, "hyperv")
    assert hyperv.get("mode") == "custom"
    assert _el(hyperv, "vendor_id").get("value") == "1234567890ab"
    assert _el(feats, "kvm/hidden").get("state") == "on"
    assert _el(feats, "msrs").get("unknown") == "fault"
    assert _el(feats, "smm").get("state") == "on"


# -- synthetic profiles ----------------------------------------------------


def _profile(**over):
    base = {
        "name": "t",
        "vm": {"memory_mib": 4096, "vcpus": 4},
        "device": {},
    }
    base.update(over)
    from vmw.profiles.schema import Profile

    return Profile.model_validate(base)


def test_no_iso_no_cdrom():
    root = build_domain_xml(_profile())
    assert not root.findall("devices/disk")


def test_gpu_passthrough_hostdev_and_rom():
    p = _profile(
        passthrough={
            "gpu": [
                {"address": "0000:01:00.0", "vbios": "/opt/vmw/firmware/vbios.rom"},
                {"address": "0000:01:00.1"},
            ]
        }
    )
    root = build_domain_xml(p)
    hostdevs = root.findall("devices/hostdev")
    assert len(hostdevs) == 2
    first = hostdevs[0]
    assert first.get("type") == "pci" and first.get("managed") == "yes"
    addr = _el(first, "source/address")
    assert addr.get("bus") == "0x01" and addr.get("function") == "0x0"
    assert _el(first, "rom").get("file") == "/opt/vmw/firmware/vbios.rom"
    # second function has no rom
    assert not hostdevs[1].findall("rom")


def test_viommu_off_by_default():
    root = build_domain_xml(_profile())
    assert not root.findall("devices/iommu")
    assert not root.findall("features/ioapic")


def test_viommu_emits_iommu_and_ioapic():
    root = build_domain_xml(_profile(device={"viommu": True}))
    iommu = _el(root, "devices/iommu")
    assert iommu.get("model") == "intel"
    driver = _el(iommu, "driver")
    assert driver.get("intremap") == "on"
    assert driver.get("caching_mode") == "on"
    # The QEMU ioapic is required for the vIOMMU's interrupt remapping.
    assert _el(root, "features/ioapic").get("driver") == "qemu"


def test_acpitable_args_resolve_to_firmware_dir():
    p = _profile(acpitable={"files": ["fake_battery.aml", "spoofed_devices.aml"]})
    args = qemu_commandline_args(p)
    tables = [args[i + 1] for i, a in enumerate(args) if a == "-acpitable"]
    assert tables == [
        "file=/opt/vmw/firmware/fake_battery.aml",
        "file=/opt/vmw/firmware/spoofed_devices.aml",
    ]


def test_serializes_and_validates_shape():
    xml = to_string(build_domain_xml(_profile()))
    assert xml.startswith(b"<?xml")
    # re-parses cleanly
    etree.fromstring(xml)


@pytest.mark.live
def test_generated_xml_passes_virt_xml_validate(tmp_path):
    import shutil
    import subprocess

    if shutil.which("virt-xml-validate") is None:
        pytest.skip("virt-xml-validate not installed")
    out = tmp_path / "dom.xml"
    out.write_bytes(to_string(build_domain_xml(load_config("example"))))
    proc = subprocess.run(
        ["virt-xml-validate", str(out), "domain"], capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode()
