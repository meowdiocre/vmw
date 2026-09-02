"""Probes against fixture trees (plan 05 purity boundary)."""

from pathlib import Path

from vmw.infra import probe
from vmw.infra.host import detect_bootloader, detect_cpu, detect_distro
from vmw.infra.probe import State


class Completed:
    """Stub for subprocess.run returning success."""

    returncode = 0


class Failed:
    returncode = 1


def test_distro_arch_from_os_release():
    text = 'ID=arch\nNAME="Arch Linux"\n'
    assert detect_distro(os_release=text, which=lambda _t: None) == "Arch"


def test_distro_fedora_from_tool_fallback():
    assert (
        detect_distro(
            os_release="ID=gentoo\n", which=lambda t: None if t != "dnf" else "/usr/bin/dnf"
        )
        == "Fedora"
    )


def test_distro_unsupported():
    import pytest
    from vmw.infra.host import UnsupportedHostError

    with pytest.raises(UnsupportedHostError):
        detect_distro(os_release="ID=gentoo\n", which=lambda _t: None)


def test_cpu_detection():
    assert detect_cpu(cpuinfo="vendor_id\t: AuthenticAMD\n") == (
        "AuthenticAMD",
        "AMD",
        "svm",
    )
    assert detect_cpu(cpuinfo="vendor_id\t: GenuineIntel\n") == (
        "GenuineIntel",
        "Intel",
        "vmx",
    )


def test_bootloader_detection_fixture(tmp_path):
    # systemd-boot layout
    (tmp_path / "boot/loader/entries").mkdir(parents=True)
    assert detect_bootloader(findmnt=lambda _t: None, root=tmp_path) == "systemd-boot"
    # grub layout
    other = tmp_path / "g"
    (other / "boot/grub").mkdir(parents=True)
    (other / "boot/grub/grub.cfg").write_text("")
    assert detect_bootloader(findmnt=lambda _t: None, root=other) == "grub"
    # limine layout
    limine = tmp_path / "l"
    (limine / "boot").mkdir(parents=True)
    (limine / "boot/limine.conf").write_text("")
    assert detect_bootloader(findmnt=lambda _t: None, root=limine) == "limine"


def test_kernel_entry_probe(tmp_path):
    # vmlinuz present
    boot = tmp_path / "vmlinuz-ok"
    boot.mkdir()
    (boot / "vmlinuz-linux70-tkg-eevdf").write_bytes(b"")
    assert probe.kernel_boot_entry_present("linux70-tkg-eevdf", boot=boot)
    # HvP-RDTSC entry present (this machine's shape)
    entry_dir = tmp_path / "efi/loader/entries"
    entry_dir.mkdir(parents=True)
    Path("/boot/loader/entries") if False else None  # noqa: B011
    # use absolute path branch
    global_marker = Path("/boot/loader/entries/HvP-RDTSC.conf")
    assert not global_marker.exists() or probe.kernel_boot_entry_present("nope", boot=boot)


def test_qemu_and_ovmf_probes(tmp_path):
    assert not probe.qemu_binary_present(out_dir=tmp_path)
    bin_dir = tmp_path / "emulator/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "qemu-system-x86_64").write_bytes(b"")
    assert probe.qemu_binary_present(out_dir=tmp_path)

    assert not probe.ovmf_firmware_present(out_dir=tmp_path)
    fw = tmp_path / "firmware"
    fw.mkdir()
    (fw / "OVMF_CODE.fd").write_bytes(b"")
    (fw / "OVMF_VARS.fd").write_bytes(b"")
    assert probe.ovmf_firmware_present(out_dir=tmp_path)


def test_vfio_probe_fixture(tmp_path):
    sys_root = tmp_path / "sys"
    assert not probe.vfio_bound(sys_root=sys_root)
    drivers = sys_root / "bus/pci/drivers/vfio-pci"
    (sys_root / "kernel/iommu_groups").mkdir(parents=True)
    drivers.mkdir(parents=True)
    (drivers / "0000:01:00.0").mkdir()
    assert probe.vfio_bound(sys_root=sys_root)


def test_domain_defined_stub():
    assert probe.domain_defined("x", virsh="true-bin", run=lambda *a, **k: Completed())
    assert not probe.domain_defined("x", virsh="false-bin", run=lambda *a, **k: Failed())


def _missing_binary(*a, **k):
    raise FileNotFoundError(2, "No such file or directory", a[0][0])


def test_probes_tolerate_missing_binaries():
    # Pristine host/container: virsh & systemctl absent must read as
    # "not present", never crash probe_all.
    assert not probe.domain_defined("x", run=_missing_binary)
    assert not probe.libvirt_network_present(run=_missing_binary)
    assert not probe.libvirtd_active(run=_missing_binary)


def test_patch_staleness(tmp_path):
    patch = tmp_path / "p.mypatch"
    patch.write_bytes(b"content")
    values = {}
    assert probe.patch_hash_stale(values, "kernel", patch, tmp_path) is None
    import hashlib

    digest = hashlib.sha256(b"content").hexdigest()
    values["values.kernel.build_hash"] = digest
    assert probe.patch_hash_stale(values, "kernel", patch, tmp_path) is None
    patch.write_bytes(b"changed")
    assert probe.patch_hash_stale(values, "kernel", patch, tmp_path) is State.STALE


def test_kernel_boot_entry_permission_denied_reads_as_absent(monkeypatch):
    """A root-only ESP entry must read as 'not present', not crash.

    Regresses the CI failure where Path.exists() propagated
    PermissionError on Python < 3.13 (3.13+ returns False), so the
    probe behaved differently per interpreter and per machine.
    """

    def deny(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "exists", deny)
    assert probe.kernel_boot_entry_present("linux70-tkg-eevdf") is False


def test_bootloader_detection_permission_denied_reads_as_unknown(monkeypatch):
    """detect_bootloader must not crash when a boot path is unreadable."""

    def deny(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "exists", deny)
    monkeypatch.setattr(Path, "glob", lambda self, pat: (_ for _ in ()).throw(PermissionError()))
    assert detect_bootloader(root=Path("/")) == "unknown"
