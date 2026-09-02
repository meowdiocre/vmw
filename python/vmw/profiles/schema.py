"""Profile schema: pydantic v2 models mirroring configs/*.yml (ADR-002).

Every field is read by genxml or a step. The schema is the doc. Dead
keys from the legacy YAML (evdev.grab_toggle, audio.mixing_engine,
vm.osinfo) are dropped; boot.order/menu are not yet wired into
<os><boot> and must be wired or removed (see below).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OnOff(StrEnum):
    """libvirt's on/off strings, kept verbatim for XML emission."""

    ON = "on"
    OFF = "off"


class YesNo(StrEnum):
    """libvirt's yes/no strings."""

    YES = "yes"
    NO = "no"


def _onoff(value: str | OnOff) -> OnOff:
    if isinstance(value, OnOff):
        return value
    return OnOff(str(value).lower())


def _yesno(value: str | YesNo) -> YesNo:
    if isinstance(value, YesNo):
        return value
    return YesNo(str(value).lower())


class _Section(BaseModel):
    """Base: strict (unknown keys are errors). The schema is the doc."""

    model_config = ConfigDict(extra="forbid")


class CpuTopology(_Section):
    sockets: int = Field(ge=1)
    cores: int = Field(ge=1)
    threads: int = Field(ge=1)


class Cpu(_Section):
    topology: CpuTopology | None = None
    check: Literal["none", "partial", "full"] = "none"
    migratable: OnOff = OnOff.OFF
    cache: Literal["passthrough", "off", "emulate"] = "passthrough"
    maxphysaddr: Literal["passthrough", "emit"] = "passthrough"

    @field_validator("migratable", mode="before")
    @classmethod
    def _coerce_migratable(cls, value):
        return _onoff(value)


class Boot(_Section):
    order: str | None = "cdrom,hd"  # TODO: wire into <os><boot> or drop
    menu: OnOff | None = OnOff.ON  # TODO: same
    loader: Path = Path("/opt/vmw/firmware/OVMF_CODE.fd")
    loader_secure: YesNo = YesNo.YES
    nvram_template: Path = Path("/opt/vmw/firmware/OVMF_VARS.fd")

    @field_validator("menu", mode="before")
    @classmethod
    def _coerce_menu(cls, value):
        return None if value is None else _onoff(value)

    @field_validator("loader_secure", mode="before")
    @classmethod
    def _coerce_secure(cls, value):
        return _yesno(value)


class Features(_Section):
    hyperv: bool = True
    kvm_hidden: bool = True
    pmu: OnOff = OnOff.OFF
    vmport: OnOff = OnOff.OFF
    smm: OnOff = OnOff.ON
    msrs_unknown: Literal["fault", "ignore", "error"] = "fault"
    ps2: OnOff = OnOff.OFF

    @field_validator("pmu", "vmport", "smm", "ps2", mode="before")
    @classmethod
    def _coerce_onoff(cls, value):
        return _onoff(value)


class Hyperv(_Section):
    mode: Literal["custom", "off", "passthrough"] = "custom"
    relaxed: OnOff = OnOff.ON
    vapic: OnOff = OnOff.ON
    spinlocks: OnOff = OnOff.ON
    spinlocks_retries: int = 8191
    vendor_id_state: OnOff = OnOff.ON
    vendor_id: str = "1234567890ab"

    @field_validator("relaxed", "vapic", "spinlocks", "vendor_id_state", mode="before")
    @classmethod
    def _coerce_onoff(cls, value):
        return _onoff(value)


class Clock(_Section):
    offset: Literal["localtime", "utc"] = "localtime"
    tsc_present: YesNo = YesNo.YES
    tsc_mode: Literal["native", "emulate", "auto", "off"] = "native"
    kvmclock_present: YesNo = YesNo.NO
    hypervclock_present: YesNo = YesNo.YES

    @field_validator("tsc_present", "kvmclock_present", "hypervclock_present", mode="before")
    @classmethod
    def _coerce_yesno(cls, value):
        return _yesno(value)


class Pm(_Section):
    suspend_to_mem: YesNo = YesNo.YES
    suspend_to_disk: YesNo = YesNo.YES

    @field_validator("suspend_to_mem", "suspend_to_disk", mode="before")
    @classmethod
    def _coerce_yesno(cls, value):
        return _yesno(value)


class Device(_Section):
    emulator: Path = Path("/opt/vmw/emulator/bin/qemu-system-x86_64")
    # vmud (the default profile) has no disk yet: genxml emits a
    # cdrom-only domain until a disk_path is set.
    disk_path: Path | None = None
    disk_size_gb: int = Field(default=150, ge=1)
    disk_bus: Literal["nvme", "sata", "virtio", "ide"] = "nvme"
    disk_cache: str = "none"
    disk_io: str = "native"
    disk_block_logical: int = 4096
    disk_block_physical: int = 4096
    nic_model: str = "e1000e"
    sound_model: str = "ich9"
    audio_type: str = "pipewire"
    graphics: str = "spice"
    video: str = "vga"
    tpm: Literal["emulator", "none"] = "emulator"
    tpm_model: str = "tpm-crb"
    memballoon: str = "none"
    # Expose a virtual IOMMU (intel VT-d) to the guest. Required for
    # Windows Kernel DMA Protection / VBS / HVCI (Vanguard On-Demand).
    # Emits <iommu> + <ioapic> and adds dmar-viommu-stealth.patch to the
    # qemu build so the DMAR table loses its QEMU signature. Off by
    # default: with no <iommu> the DMAR table is never emitted and that
    # detection branch stays closed.
    viommu: bool = False


class Paths(_Section):
    downloads_dir: Path = Path("/var/lib/libvirt/boot")
    iso_path: Path | None = None


class Patches(_Section):
    # Empty means "pick the patch for the host CPU" (Intel/AMD) at build
    # time, so one profile is portable across machines. Set a value only to
    # force a specific file in patches/{Kernel,QEMU,EDK2}/.
    kernel: str = ""
    qemu: str = ""
    edk2: str = ""


class SmBios(_Section):
    file: Path = Path("/opt/vmw/firmware/smbios.bin")


class Evdev(_Section):
    enabled: bool = False
    # grab_toggle dropped (dead key, plan 01)


class Audio(_Section):
    pipewire: bool = True
    # mixing_engine dropped (dead key, plan 01)


class Machine(_Section):
    """New field: full machine.args passthrough (plan 01)."""

    args: str = "pc-q35-11.0,usb=off,vmport=off,smm=on,i8042=off"


class PassthroughGpu(_Section):
    address: str  # "0000:01:00.0"
    vbios: Path | None = None


class Passthrough(_Section):
    gpu: list[PassthroughGpu] = Field(default_factory=list)


class Acpitable(_Section):
    # profile field: list of .aml file names under patches/QEMU/
    files: list[str] = Field(default_factory=list)


class Vm(_Section):
    # osinfo dropped (dead key, plan 01)
    memory_mib: int = Field(ge=16)
    vcpus: int = Field(ge=1)


class Profile(_Section):
    name: str
    vm: Vm
    cpu: Cpu = Field(default_factory=Cpu)
    boot: Boot = Field(default_factory=Boot)
    features: Features = Field(default_factory=Features)
    hyperv: Hyperv = Field(default_factory=Hyperv)
    clock: Clock = Field(default_factory=Clock)
    pm: Pm = Field(default_factory=Pm)
    device: Device
    paths: Paths = Field(default_factory=Paths)
    patches: Patches = Field(default_factory=Patches)
    smbios: SmBios = Field(default_factory=SmBios)
    evdev: Evdev = Field(default_factory=Evdev)
    audio: Audio = Field(default_factory=Audio)
    machine: Machine = Field(default_factory=Machine)
    passthrough: Passthrough = Field(default_factory=Passthrough)
    acpitable: Acpitable = Field(default_factory=Acpitable)

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        if not value or not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("profile name must be alphanumeric/dash/underscore")
        return value

    @property
    def domain_name(self) -> str:
        return self.name
