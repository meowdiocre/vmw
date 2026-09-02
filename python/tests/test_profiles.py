"""Profiles: schema validation over the real configs + fixture corpus."""

from pathlib import Path

import pytest
from vmw.profiles.loader import ProfileError, discover, load_config
from vmw.profiles.schema import Profile

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_profiles_load():
    for name in discover():
        profile = load_config(name)
        assert profile.name == name
        assert profile.vm.vcpus >= 1


def test_example_fields():
    profile = load_config("example")
    assert profile.vm.memory_mib == 8192
    assert profile.cpu.topology is not None
    assert profile.cpu.topology.cores == 4
    assert profile.boot.loader == Path("/opt/vmw/firmware/OVMF_CODE.fd")
    assert profile.features.hyperv is True
    assert profile.hyperv.vendor_id == "1234567890ab"
    assert profile.clock.tsc_mode == "native"
    # patches unpinned: empty means "derive the Intel/AMD patch from the host"
    assert profile.patches.kernel == ""
    assert profile.patches.qemu == ""
    assert profile.patches.edk2 == ""
    assert profile.device.nic_model == "e1000e"


def test_defaults_merge_and_override():
    """Profiles inherit configs/_defaults.yml; their own keys win."""
    apt = load_config("example")
    vmud = load_config("vmud")

    # inherited from _defaults (present in neither thin profile)
    assert apt.device.nic_model == "e1000e"
    assert vmud.device.nic_model == "e1000e"
    assert apt.features.smm.value == "on"
    assert vmud.boot.loader == Path("/opt/vmw/firmware/OVMF_CODE.fd")

    # overridden per profile (nested device dict merges key-by-key)
    assert apt.device.disk_size_gb == 150
    assert vmud.device.disk_size_gb == 500
    assert apt.device.viommu is True
    assert vmud.device.viommu is False  # schema default, not set by either file
    assert apt.vm.memory_mib == 8192
    assert vmud.vm.memory_mib == 12288


def test_discover_excludes_defaults_base():
    """_defaults.yml is a base, not a selectable profile."""
    assert "_defaults" not in discover()


def test_dead_keys_rejected():
    """The schema is the doc: unknown keys are errors (plan 01)."""
    import pytest as _pytest
    import yaml

    raw = {
        "name": "x",
        "vm": {"memory_mib": 512, "vcpus": 1},
        "device": {"disk_path": "/tmp/d.qcow2"},
        "evdev": {"enabled": False, "grab_toggle": "ctrl-ctrl"},
    }
    with _pytest.raises(ProfileError):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
            yaml.safe_dump(raw, handle)
            path = handle.name
        try:
            load_config(Path(path).stem, configs_dir=Path(path).parent)
        finally:
            Path(path).unlink()


import tempfile  # noqa: E402


def test_missing_profile_raises():
    with pytest.raises(ProfileError, match="not found"):
        load_config("does-not-exist")


def test_discover_finds_configs():
    names = discover()
    assert "example" in names
    assert "vmud" in names


def test_new_machine_and_passthrough_fields():
    """New profile fields (machine.args, passthrough, acpitable) parse."""
    raw = {
        "name": "newfields",
        "vm": {"memory_mib": 1024, "vcpus": 2},
        "device": {"disk_path": "/tmp/n.qcow2"},
        "machine": {"args": "pc-q35-11.0,usb=off,vmport=off,smm=on,i8042=off"},
        "acpitable": {"files": ["fake_battery.aml", "spoofed_devices.aml"]},
        "passthrough": {
            "gpu": [{"address": "0000:01:00.0", "vbios": "/opt/vmw/firmware/vbios.rom"}]
        },
    }
    profile = Profile.model_validate(raw)
    assert profile.machine.args.startswith("pc-q35-11.0")
    assert profile.passthrough.gpu[0].address == "0000:01:00.0"
    assert profile.acpitable.files == ["fake_battery.aml", "spoofed_devices.aml"]


def test_bad_name_rejected():
    with pytest.raises(ValueError):
        Profile.model_validate(
            {
                "name": "bad name!",
                "vm": {"memory_mib": 512, "vcpus": 1},
                "device": {"disk_path": "/tmp/d.qcow2"},
            }
        )
