"""Typed <domain> emitter: build_domain_xml(Profile).

Element-for-element the config-driven subset of a vmw domain, rendered
from a validated pydantic Profile. Hand-added live artifacts that no
profile field drives (hugepages, cputune pinning, ioapic, rtc/pit/hpet
timers, expanded hyperv enlightenments, seclabel) are NOT emitted here.
They are documented as ADR-006 notes rather than silently reproduced.

Schema-order note: libvirt wants <os> before <features>/<clock>/<pm>,
and <cpu> after <features>. Element order below follows the domain
schema so virt-xml-validate passes.
"""

from __future__ import annotations

from lxml import etree

from vmw.genxml.qemu_args import qemu_commandline_args
from vmw.profiles.schema import Profile

QEMU_NS = "http://libvirt.org/schemas/domain/qemu/1.0"


def _e(parent, tag, **attrs):
    el = etree.SubElement(parent, tag)
    for key, value in attrs.items():
        if value is not None:
            el.set(key, str(value))
    return el


def _text(parent, tag, value, **attrs):
    el = _e(parent, tag, **attrs)
    el.text = str(value)
    return el


def _qemu_el(parent, tag, **attrs):
    el = etree.SubElement(parent, f"{{{QEMU_NS}}}{tag}")
    for key, value in attrs.items():
        if value is not None:
            el.set(key, str(value))
    return el


def _pci_addr(pci: str) -> dict[str, str]:
    """'0000:01:00.0' -> libvirt address attrs (domain/bus/slot/function)."""
    domain, bus, slot_func = pci.split(":")
    slot, _, function = slot_func.partition(".")
    return {
        "domain": f"0x{domain}",
        "bus": f"0x{bus}",
        "slot": f"0x{slot}",
        "function": f"0x{function or '0'}",
    }


def build_domain_xml(profile: Profile) -> etree._Element:
    """Render the domain XML for a validated Profile."""
    root = etree.Element("domain", type="kvm", nsmap={"qemu": QEMU_NS})
    _text(root, "name", profile.domain_name)

    # Memory (MiB profile -> KiB XML)
    mem_kib = profile.vm.memory_mib * 1024
    _text(root, "memory", mem_kib, unit="KiB")
    _text(root, "currentMemory", mem_kib, unit="KiB")
    _e(root, "vcpu", placement="static").text = str(profile.vm.vcpus)

    # OS / boot (before features/clock/pm in schema order)
    machine = profile.machine.args.split(",", 1)[0]  # <type machine=...> takes the base
    osel = _e(root, "os")
    _e(osel, "type", arch="x86_64", machine=machine).text = "hvm"
    _e(
        osel,
        "loader",
        readonly="yes",
        type="pflash",
        secure=profile.boot.loader_secure,
    ).text = str(profile.boot.loader)
    _e(osel, "nvram", template=str(profile.boot.nvram_template))
    for dev in (profile.boot.order or "").split(","):
        dev = dev.strip()
        if dev:
            _e(osel, "boot", dev=dev)

    feat = profile.features
    feat_el = _e(root, "features")
    _e(feat_el, "acpi")
    _e(feat_el, "apic")
    if feat.hyperv:
        hv = profile.hyperv
        hyperv = _e(feat_el, "hyperv", mode=hv.mode)
        _e(hyperv, "relaxed", state=hv.relaxed)
        _e(hyperv, "vapic", state=hv.vapic)
        _e(hyperv, "spinlocks", state=hv.spinlocks, retries=hv.spinlocks_retries)
        _e(hyperv, "vendor_id", state=hv.vendor_id_state, value=hv.vendor_id)
    if feat.kvm_hidden:
        kvm = _e(feat_el, "kvm")
        _e(kvm, "hidden", state="on")
    _e(feat_el, "pmu", state=feat.pmu)
    _e(feat_el, "vmport", state=feat.vmport)
    _e(feat_el, "smm", state=feat.smm)
    _e(feat_el, "msrs", unknown=feat.msrs_unknown)
    _e(feat_el, "ps2", state=feat.ps2)
    if profile.device.viommu:
        # The QEMU ioapic is required for the vIOMMU's interrupt remapping.
        _e(feat_el, "ioapic", driver="qemu")

    # CPU (after features)
    cpu = _e(
        root,
        "cpu",
        mode="host-passthrough",
        check=profile.cpu.check,
        migratable=profile.cpu.migratable,
    )
    topo = profile.cpu.topology
    if topo is not None:
        _e(
            cpu,
            "topology",
            sockets=topo.sockets,
            dies=1,
            clusters=1,
            cores=topo.cores,
            threads=topo.threads,
        )
    _e(cpu, "cache", mode=profile.cpu.cache)
    _e(cpu, "maxphysaddr", mode=profile.cpu.maxphysaddr)

    clk = profile.clock
    clock = _e(root, "clock", offset=clk.offset)
    _e(clock, "timer", name="tsc", present=clk.tsc_present, mode=clk.tsc_mode)
    _e(clock, "timer", name="kvmclock", present=clk.kvmclock_present)
    _e(clock, "timer", name="hypervclock", present=clk.hypervclock_present)

    pm = _e(root, "pm")
    _e(pm, "suspend-to-mem", enabled=profile.pm.suspend_to_mem)
    _e(pm, "suspend-to-disk", enabled=profile.pm.suspend_to_disk)

    devices = _e(root, "devices")
    _e(devices, "emulator").text = str(profile.device.emulator)
    if profile.device.viommu:
        # intel VT-d vIOMMU. intremap feeds the QEMU ioapic; caching_mode
        # is mandatory when a device is also passed through, or the
        # passthrough breaks. Model intel: QEMU's amd-iommu is far less
        # complete with assigned devices.
        iommu = _e(devices, "iommu", model="intel")
        _e(iommu, "driver", intremap="on", caching_mode="on")
    _build_devices(devices, profile)

    args = qemu_commandline_args(profile)
    if args:
        qemu = _qemu_el(root, "commandline")
        for value in args:
            _qemu_el(qemu, "arg", value=value)

    return root


def _build_devices(devices, profile: Profile) -> None:
    dev = profile.device

    # Boot disk (skipped when the profile has no disk_path yet; vmud
    # emits a cdrom-only domain until a disk image is attached).
    if dev.disk_path is not None:
        disk = _e(devices, "disk", type="file", device="disk")
        _e(
            disk,
            "driver",
            name="qemu",
            type="qcow2",
            cache=dev.disk_cache,
            io=dev.disk_io,
            discard="unmap",
        )
        _e(disk, "source", file=str(dev.disk_path))
        bus = dev.disk_bus
        target_dev = "nvme0n1" if bus == "nvme" else "sda"
        _e(disk, "target", dev=target_dev, bus=bus)
        _e(
            disk,
            "blockio",
            logical_block_size=dev.disk_block_logical,
            physical_block_size=dev.disk_block_physical,
        )

    if profile.paths.iso_path is not None:
        cd = _e(devices, "disk", type="file", device="cdrom")
        _e(cd, "driver", name="qemu", type="raw")
        _e(cd, "source", file=str(profile.paths.iso_path))
        cd_dev = "sdb" if dev.disk_path is not None else "sda"
        _e(cd, "target", dev=cd_dev, bus="sata")
        _e(cd, "readonly")

    net = _e(devices, "interface", type="network")
    _e(net, "source", network="default")
    _e(net, "model", type=dev.nic_model)

    _e(devices, "input", type="mouse", bus="usb")
    _e(devices, "input", type="keyboard", bus="usb")

    if profile.audio.pipewire:
        _e(devices, "sound", model=dev.sound_model)
        _e(devices, "audio", type="pipewire", id="1")

    _e(devices, "graphics", type=dev.graphics)
    vid = _e(devices, "video")
    _e(vid, "model", type=dev.video)

    if dev.tpm != "none":
        tpm = _e(devices, "tpm", model=dev.tpm_model)
        _e(tpm, "backend", type="emulator")

    # GPU passthrough: one <hostdev> per function, <rom/> when a vbios
    # is given (the live RTX 3050 Ti pair at 01:00.0/.1).
    for gpu in profile.passthrough.gpu:
        hostdev = _e(devices, "hostdev", mode="subsystem", type="pci", managed="yes")
        _e(hostdev, "driver", name="vfio")
        source = _e(hostdev, "source")
        _e(source, "address", **_pci_addr(gpu.address))
        if gpu.vbios is not None:
            _e(hostdev, "rom", file=str(gpu.vbios))

    _e(devices, "serial", type="pty")
    _e(devices, "console", type="pty")

    _e(devices, "memballoon", model=dev.memballoon)


def to_string(root: etree._Element) -> bytes:
    """Serialize with declaration + pretty printing (dumpxml-style)."""
    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )
