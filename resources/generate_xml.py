#!/usr/bin/env python3
"""Generate a libvirt domain XML from a VMW YAML profile.

Reads configs/<profile>.yml and emits a libvirt domain XML to stdout
(or a file with --output). Replaces the fragile string-building in
modules/deploy.sh.

Usage:
  generate_xml.py <profile> [--output <file>] [--domain-name <name>]

The XML mirrors what modules/deploy.sh built via virt-install, but as a
deterministic document. It is NOT a full replacement for virt-install's
installer flow (boot order, cdrom) — it emits the resulting domain XML.
"""
import argparse
import os
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write("error: PyYAML required (pip install pyyaml)\n")
    sys.exit(1)

try:
    from lxml import etree
except ImportError:
    sys.stderr.write("error: lxml required (pip install lxml)\n")
    sys.exit(1)

CONFIGS_DIR = "configs"
DEFAULT_LOADER = "/opt/AutoVirt/firmware/OVMF_CODE.fd"
DEFAULT_NVRAM = "/opt/AutoVirt/firmware/OVMF_VARS.fd"
DEFAULT_EMULATOR = "/opt/AutoVirt/emulator/bin/qemu-system-x86_64"


QEMU_NS = "http://libvirt.org/schemas/domain/qemu/1.0"


def e(parent, tag, **attrs):
    el = etree.SubElement(parent, tag)
    for key, value in attrs.items():
        if value is not None:
            el.set(key, str(bool_str(value)))
    return el


def qemu_el(parent, tag, **attrs):
    el = etree.SubElement(parent, f"{{{QEMU_NS}}}{tag}")
    for key, value in attrs.items():
        if value is not None:
            el.set(key, str(bool_str(value)))
    return el


def text(parent, tag, value, **attrs):
    el = e(parent, tag, **attrs)
    el.text = str(value)
    return el


def bool_str(value):
    """Map python/YAML booleans to libvirt on/off strings."""
    if isinstance(value, bool):
        return "on" if value else "off"
    return value


def s(el, **attrs):
    for key, value in attrs.items():
        if value is not None:
            el.set(key, str(bool_str(value)))
    return el


def build_xml(cfg, domain_name=None):
    root = etree.Element("domain", type="kvm",
                         nsmap={"qemu": QEMU_NS})
    domain_name = domain_name or cfg.get("name", "vmw")
    text(root, "name", domain_name)

    vm = cfg.get("vm", {})
    if vm.get("uuid"):
        text(root, "uuid", vm["uuid"])

    # Memory (MiB from config -> KiB in XML)
    mem_mib = int(vm.get("memory_mib", 8192))
    text(root, "memory", mem_mib * 1024, unit="KiB")
    text(root, "currentMemory", mem_mib * 1024, unit="KiB")

    vcpus = vm.get("vcpus", 8)
    e(root, "vcpu", placement="static").text = str(vcpus)

    # CPU
    cpu = root.makeelement("cpu", {})
    topo = cfg.get("cpu", {}).get("topology", {})
    e(cpu, "topology",
      sockets=topo.get("sockets", 1),
      dies=topo.get("dies", 1),
      clusters=topo.get("clusters", 1),
      cores=topo.get("cores", 4),
      threads=topo.get("threads", 2))
    e(cpu, "cache", mode=cfg.get("cpu", {}).get("cache", "passthrough"))
    e(cpu, "maxphysaddr", mode=cfg.get("cpu", {}).get("maxphysaddr", "passthrough"))
    s(cpu, check=cfg.get("cpu", {}).get("check", "none"),
      migratable=cfg.get("cpu", {}).get("migratable", "off"))    # CPU features (from old deploy.sh: svm/vmx, topoext, invtsc, hypervisor, ssbd...)
    feats = cfg.get("cpu", {}).get("features", {})
    for name, policy in feats.items():
        e(cpu, "feature", name=name, policy=policy)
    root.append(cpu)

    # OS / boot (must come before clock/features/pm in schema order)
    boot = cfg.get("boot", {})
    osel = e(root, "os")
    e(osel, "type", machine=cfg.get("machine", "pc-q35-11.0")).text = "hvm"
    loader = boot.get("loader", DEFAULT_LOADER)
    e(osel, "loader", readonly="yes", type="pflash", secure=boot.get("loader_secure", "yes")).text = loader
    nvram = boot.get("nvram_template", DEFAULT_NVRAM)
    e(osel, "nvram").text = nvram

    # Clock
    clk = cfg.get("clock", {})
    clock = e(root, "clock", offset=clk.get("offset", "localtime"))
    for timer in ("tsc", "kvmclock", "hypervclock"):
        present = clk.get(f"{timer}_present")
        if present:
            e(clock, "timer", name=timer, present=present, mode=clk.get(f"{timer}_mode"))

    # Features
    feat = cfg.get("features", {})
    feat_el = e(root, "features")
    if feat.get("hyperv", False) is True:
        hv = cfg.get("hyperv", {})
        hyperv = e(feat_el, "hyperv", mode=hv.get("mode", "custom"))
        e(hyperv, "relaxed", state=hv.get("relaxed", "on"))
        e(hyperv, "vapic", state=hv.get("vapic", "on"))
        e(hyperv, "spinlocks", state=hv.get("spinlocks", "on"),
          retries=hv.get("spinlocks_retries", 8191))
        e(hyperv, "vendor_id", state=hv.get("vendor_id_state", "on"),
          value=hv.get("vendor_id", "1234567890ab"))

    if feat.get("kvm_hidden", True) is True:
        kvm = e(feat_el, "kvm")
        e(kvm, "hidden", state="on")

    for fname in ("pmu", "vmport"):
        if fname in feat:
            e(feat_el, fname, state=feat[fname])
    if "smm" in feat:
        e(feat_el, "smm", state=feat["smm"])
    if "msrs_unknown" in feat:
        e(feat_el, "msrs", unknown=feat["msrs_unknown"])
    if "ps2" in feat:
        e(feat_el, "ps2", state=feat["ps2"])

    # PM
    pm = cfg.get("pm", {})
    pmel = e(root, "pm")
    e(pmel, "suspend-to-mem", enabled=pm.get("suspend_to_mem", "yes"))
    e(pmel, "suspend-to-disk", enabled=pm.get("suspend_to_disk", "yes"))

    # Devices
    devices = e(root, "devices")
    e(devices, "emulator").text = cfg.get("device", {}).get("emulator", DEFAULT_EMULATOR)

    # Disk
    disk = cfg.get("device", {})
    d = e(devices, "disk", type="file", device="disk")
    e(d, "driver", name="qemu", type="qcow2", cache=disk.get("disk_cache", "none"),
      io=disk.get("disk_io", "native"), discard="unmap")
    e(d, "source", file=f"/var/lib/libvirt/images/{domain_name}.qcow2")
    e(d, "target", dev="nvme0n1", bus=disk.get("disk_bus", "nvme"))
    e(d, "blockio",
      logical_block_size=disk.get("disk_block_logical", 4096),
      physical_block_size=disk.get("disk_block_physical", 4096))
    e(d, "serial").text = disk.get("serial", "1233659")

    # CD-ROM
    iso = cfg.get("paths", {}).get("iso_path")
    if iso:
        cd = e(devices, "disk", type="file", device="cdrom")
        e(cd, "driver", name="qemu", type="raw")
        e(cd, "source", file=iso)
        e(cd, "target", dev="sda", bus="sata")
        e(cd, "readonly")

    # NIC
    nic = disk.get("nic_model", "e1000e")
    net = e(devices, "interface", type="network")
    e(net, "source", network="default")
    e(net, "model", type=nic)
    if disk.get("mac"):
        e(net, "mac", address=disk["mac"])

    # Input (USB, evdev passthrough)
    e(devices, "input", type="mouse", bus="usb")
    e(devices, "input", type="keyboard", bus="usb")

    evdev = cfg.get("evdev", {})
    if evdev.get("enabled", False) is True:
        for dev in evdev.get("devices", []):
            e(devices, "input", type="evdev", bus="virtio")
            inp = e(devices, "input", type="passthrough")
            e(inp, "source", dev=dev)

    # Audio (PipeWire)
    audio = cfg.get("audio", {})
    if audio.get("pipewire", False) is True:
        e(devices, "sound", model=disk.get("sound_model", "ich9"))
        e(devices, "audio", type="pipewire", id="1",
          runtimeDir=f"/run/user/{os.getuid()}")

    # Graphics / video
    e(devices, "graphics", type=disk.get("graphics", "spice"))
    vid = e(devices, "video")
    e(vid, "model", type=disk.get("video", "vga"))

    # TPM
    if disk.get("tpm"):
        tpm = e(devices, "tpm", model=disk.get("tpm_model", "tpm-crb"))
        e(tpm, "backend", type="emulator")

    # Console / serial
    e(devices, "console", type="pty")
    e(devices, "serial", type="pty")

    # qemu:commandline (smbios)
    smbios = cfg.get("smbios", {}).get("file")
    if smbios:
        qemu = qemu_el(root, "commandline")
        qemu_el(qemu, "arg", value="-smbios")
        qemu_el(qemu, "arg", value=f"file={smbios}")

    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="configs/<profile>.yml (without .yml)")
    parser.add_argument("--output", "-o", help="write XML to this file")
    parser.add_argument("--domain-name", help="override domain name")
    args = parser.parse_args()

    cfg_path = os.path.join(CONFIGS_DIR, f"{args.profile}.yml")
    try:
        with open(cfg_path) as handle:
            cfg = yaml.safe_load(handle) or {}
    except OSError as exc:
        sys.stderr.write(f"error: cannot read {cfg_path}: {exc}\n")
        sys.exit(1)

    xml = etree.tostring(
        build_xml(cfg, domain_name=args.domain_name),
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )
    if args.output:
        with open(args.output, "wb") as handle:
            handle.write(xml)
        print(f"Wrote {args.output}")
    else:
        sys.stdout.write(xml.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
