# QEMU

`patches/QEMU/AMD-v11.0.3.patch` and `patches/QEMU/Intel-v11.0.3.patch`
change the values QEMU exposes to the guest through CPUID, ACPI
tables, and SMBIOS. `steps/qemu.py` clones QEMU, applies the patch,
builds it, and rewrites SMBIOS/ACPI from host data.

## Hypervisor bit

`CPUID.1:ECX[31]` is the universal "a hypervisor is present" flag.
The domain XML clears it:

```xml
<cpu>
  <feature policy="disable" name="hypervisor"/>
</cpu>
```

## KVM signature and feature bits

Leaf `0x40000000` (the `KVMKVMKVM` signature) and leaf `0x40000001`
(KVM feature bits) are hidden from the guest's own CPUID view:

```xml
<features>
  <kvm>
    <hidden state="on"/>
  </kvm>
</features>
```

Reference: [`kvm_para.h`](https://gitlab.com/qemu-project/qemu/-/blob/master/include/standard-headers/asm-x86/kvm_para.h)

## KVM PV enforce CPUID

`kvm-pv-enforce-cpuid=on` makes `target/i386/kvm/kvm.c` call
`kvm_vcpu_enable_cap` with `KVM_CAP_ENFORCE_PV_FEATURE_CPUID`. KVM
then enforces paravirtual CPUID advertisement strictly: if the guest
touches a KVM PV MSR (range `0x4b564d00` to `0x4b564d08`) for a
feature that leaf `0x40000001` did not advertise, KVM injects a
`#GP` into the guest.

```xml
<qemu:commandline>
  <qemu:arg value='-cpu'/>
  <qemu:arg value='host,kvm-pv-enforce-cpuid=on'/>
</qemu:commandline>
```

References:
[`kvm.c`](https://github.com/qemu/qemu/raw/refs/heads/master/target/i386/kvm/kvm.c),
[`kvm-pv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/kvm-pv.rst)

## Hyper-V enlightenments

`<hyperv mode='custom'>` sets: relaxed, vapic, spinlocks (4095),
vpindex, runtime, synic, stimer, reset, frequencies,
reenlightenment. Libvirt 12.5 additionally recognizes `time` and
`tlbflush`; the nested-specific enlightenments (`stimer-direct`,
`tlbflush-direct`, `emsr-bitmap`, `xmm-input`) need a newer libvirt
or raw QEMU arguments.

Reference: [`hyperv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/hyperv.rst)

## ACPI tables and SMBIOS

`steps/qemu.py` reads the host's own FADT at
`/sys/firmware/acpi/tables/FACP` and copies the OEM ID, OEM table
ID, creator ID, and power-management profile into the guest's ACPI
tables. `fake_battery.aml` and `spoofed_devices.aml` are injected
through `-acpitable`. SMBIOS strings are rewritten from host DMI
data (`spoof_smbios()` in `steps/qemu.py`).

## Power capabilities (`POWER_CAPABILITIES`)

VMAware's `power_capabilities()` reads `NtPowerInformation` /
`SystemPowerCapabilities` and classifies the result:

| Pattern | Verdict |
|---|---|
| `(S0 \|\| S3) && (S4 \|\| HiberFilePresent)` | physical |
| `!(S0\|\|S3\|\|S4\|\|Hiber) && (S1\|\|S2)` | VM |
| nothing supported | VM |

A Windows guest running as a Hyper-V root partition hands power
management to the hypervisor, which drops S3 and S4 support
regardless of the ACPI FADT flags QEMU advertises — confirmed with
`powercfg /a` inside the guest, which reports S3 and hibernate
blocked by the hypervisor, not the firmware. Raising the QEMU FADT
revision to enable `LOW_POWER_S0_IDLE_CAPABLE` does not change that
result, since Windows only reads the flag at ACPI revision 5+ and a
mismatched sleep-register layout at that revision can hang guest
boot.

The registry key `PlatformAoAcOverride` sets S0, which the check
accepts on its own — `S0 = true` fails both VM patterns above, and
VMAware's own manufacturer check then passes on `smbios.bin`'s
`LENOVO` string:

```
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Power" ^
  /v PlatformAoAcOverride /t REG_DWORD /d 1 /f
```

This is a registry artifact, not a hardware property, so a future
VMAware release could read the same key.
