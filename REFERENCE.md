# VMW Reference: Detection Surfaces and Upstream Sources

Source links, spec references, and build details for each layer we
patch: QEMU, OVMF firmware, the TPM stack, and the kernel. Use this
when you need to find where a value comes from upstream.

`README.md` covers how to run the tool. `RESEARCH.md` covers what we
changed and why. This file is the lookup table behind both.



---

## 1. QEMU (emulator)

### Hypervisor bit

`CPUID.1:ECX[31]` is the universal "a hypervisor is present" flag.
Clear it:

```bash
qemu-system-x86_64 -cpu host,-hypervisor
```

```xml
<cpu>
  <feature policy="disable" name="hypervisor"/>
</cpu>
```

### KVM signature and feature bits

Hides leaf `0x40000000` (the `KVMKVMKVM` signature) and leaf
`0x40000001` (KVM feature bits).

```bash
qemu-system-x86_64 -cpu host,kvm=off
```

```xml
<features>
  <kvm>
    <hidden state="on"/>
  </kvm>
</features>
```

Reference: [`kvm_para.h`](https://gitlab.com/qemu-project/qemu/-/blob/master/include/standard-headers/asm-x86/kvm_para.h)

### KVM PV enforce CPUID

Setting this property makes `target/i386/kvm/kvm.c` call
`kvm_vcpu_enable_cap` with `KVM_CAP_ENFORCE_PV_FEATURE_CPUID`. KVM
then enforces paravirtual CPUID advertisement strictly: if the guest
touches a KVM PV MSR (range `0x4b564d00` to `0x4b564d08`) for a
feature that leaf `0x40000001` did not advertise, KVM injects a
`#GP` into the guest. The guest cannot use paravirtual features it
was never offered.

```bash
qemu-system-x86_64 -cpu host,kvm-pv-enforce-cpuid=on
```

```xml
<qemu:commandline>
  <qemu:arg value='-cpu'/>
  <qemu:arg value='host,kvm-pv-enforce-cpuid=on'/>
</qemu:commandline>
```

References:
[`kvm.c`](https://github.com/qemu/qemu/raw/refs/heads/master/target/i386/kvm/kvm.c),
[`kvm-pv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/kvm-pv.rst),
[`#GP`](https://en.wikipedia.org/wiki/General_protection_fault)

### Hyper-V enlightenments

Reference: [`hyperv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/hyperv.rst)

See `RESEARCH.md` §8 for which enlightenments libvirt 12.5 accepts
on this host.

---

## 2. EDK2 / OVMF (firmware)

Build docs:
[common instructions](https://github.com/tianocore/tianocore.github.io/wiki/Common-instructions),
[how to build OVMF](https://github.com/tianocore/tianocore.github.io/wiki/How-to-build-OVMF),
[OvmfPkg](https://github.com/tianocore/edk2/tree/master/OvmfPkg)

### Build arguments

```bash
build -a X64 -p OvmfPkg/OvmfPkgX64.dsc -b RELEASE -t GCC -n 0 -s \
  --define SECURE_BOOT_ENABLE=TRUE \
  --define SMM_REQUIRE=TRUE \
  --define TPM1_ENABLE=TRUE \
  --define TPM2_ENABLE=TRUE
```

Matching domain XML:

```xml
<features>
  <smm state="on"/>
</features>
...
<tpm model="tpm-crb">
  <backend type="emulator" version="2.0"/>
</tpm>
```

### Distro NVRAM templates

Installed by `pacman -S edk2-ovmf`:

```
/usr/share/edk2/x64/MICROVM.4m.fd
/usr/share/edk2/x64/OVMF.4m.fd
/usr/share/edk2/x64/OVMF_CODE.4m.fd
/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd
/usr/share/edk2/x64/OVMF_VARS.4m.fd
```

We do not use these. `modules/edk2.sh` builds our own and installs
to `/opt/vmw/firmware/`.

### Boot logo BMP rules

The EDK2 image decoder rejects anything that fails these checks, so
`modules/edk2.sh` validates a custom logo before copying it in:

- Bytes `0` to `1` must be `0x42 0x4D` (`BM`).
- Bit depth must be `1`, `4`, `8`, or `24`.
- Compression must be `0`.
- Width and height must be 65535 or less.

Source:
[`GenC.py#L1892`](https://github.com/tianocore/edk2/blob/master/BaseTools/Source/Python/AutoGen/GenC.py#L1892)

### Secure Boot key enrollment

Microsoft's published objects:
[secureboot_objects](https://github.com/microsoft/secureboot_objects).
`PreSignedObjects` holds PK/KEK/DB `.der` certificates.
`PostSignedObjects` holds
[`DBXUpdate.bin`](https://github.com/microsoft/secureboot_objects/blob/main/PostSignedObjects/DBX/amd64/DBXUpdate.bin).

EDK2's own enrollment app:
[`EnrollDefaultKeys`](https://github.com/tianocore/edk2/tree/master/OvmfPkg#readme)
(`OvmfPkg/EnrollDefaultKeys/EnrollDefaultKeys.{c,h,inf}`),
plus `OvmfPkg/OvmfPkg.dec` and
`OvmfPkg/Include/Guid/OvmfPkKek1AppPrefix.h`.

**Two approaches exist, and we switched between them.** The older
script downloaded Microsoft's certificates and enrolled them into a
qcow2-converted `OVMF_VARS`. The current `build_ovmf()` in
`modules/edk2.sh` instead reads *this host's own* EFI keys out of
`/sys/firmware/efi/efivars/`, writes them to JSON, and injects them
into a raw `.fd` with `virt-fw-vars --set-json`. The current approach
matches the host exactly, which is what we want for detection work.
The full old script is in git history at
`git show HEAD:modules/README.md`.

Tooling:
[UEFI variable store](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#uefi-variable-store),
[`virt-fw-vars` man page](https://man.archlinux.org/man/extra/virt-firmware/virt-fw-vars.1.en),
[`efijson.py`](https://gitlab.com/kraxel/virt-firmware/-/blob/master/virt/firmware/efi/efijson.py)

### "Last BIOS time: 0.0"

Task Manager shows a zero BIOS time because stock OVMF omits the
FPDT module. To make it report a plausible number, add the FPDT DXE
to the ACPI support section of `OvmfPkg/OvmfPkgX64.dsc`:

```
MdeModulePkg/Universal/Acpi/AcpiTableDxe/AcpiTableDxe.inf
OvmfPkg/AcpiPlatformDxe/AcpiPlatformDxe.inf
!if $(STANDALONE_MM_ENABLE) != TRUE
MdeModulePkg/Universal/Acpi/S3SaveStateDxe/S3SaveStateDxe.inf
MdeModulePkg/Universal/Acpi/BootScriptExecutorDxe/BootScriptExecutorDxe.inf
!endif
MdeModulePkg/Universal/Acpi/BootGraphicsResourceTableDxe/BootGraphicsResourceTableDxe.inf
MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.inf   <-- add
```

Implementation:
`MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.c`.
Related timeout logic: `GetFrontPageTimeoutFromQemu` in
`OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c`.

### MOR / MORLock

Memory Overwrite Request control, expected on real Secure Boot
systems:

- [OvmfPkg README, line 160](https://github.com/tianocore/edk2/blob/master/OvmfPkg/README#L160)
- [How to enable security](https://github.com/tianocore/tianocore.github.io/wiki/How-to-Enable-Security)
- [`MemoryOverwriteControl`](https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteControl)
- [`MemoryOverwriteRequestControlLock`](https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteRequestControlLock)
- [`MorLock.dsc.inc`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Dsc/MorLock.dsc.inc)
- [`MorLock.fdf.inc`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Fdf/MorLock.fdf.inc)

### OVMF TPM support

- [`OvmfPkgX64.dsc#L39`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/OvmfPkgX64.dsc#L39)
- [`OvmfTpmDefines.dsc.inc`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Dsc/OvmfTpmDefines.dsc.inc)

### Boot order variable

`VMMBootOrderNNNN` (`L"BootOrder%04x"`) is built in
`OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c`.

### Specifications and GUIDs

- [UEFI specifications index](https://uefi.org/specifications)
- [ACPI 6.6](https://uefi.org/sites/default/files/resources/ACPI_Spec_6.6.pdf)
- [UEFI 2.11](https://uefi.org/sites/default/files/resources/UEFI_Spec_Final_2.11.pdf)

| Variable name | GUID |
|---|---|
| `EFI_GLOBAL_VARIABLE` | `8be4df61-93ca-11d2-aa0d-00e098032b8c` |
| `EFI_IMAGE_SECURITY_DATABASE_GUID` | `d719b2cb-3d3a-4596-a3bc-dad00e67656f` |

### Host paths

| What | Where |
|---|---|
| Writable NVRAM generated per domain | `/var/lib/libvirt/qemu/nvram` |
| Disk images | `/var/lib/libvirt/images/` |
| Our built firmware | `/opt/vmw/firmware/` |

---

## 3. TPM (libtpms / swtpm)

TPM identity comes from two layers. Change both, or the guest sees a
mismatch.

### Layer 1: libtpms runtime identity

This is what Windows reads through `TPM2_GetCapability`: `tpm.msc`,
`Get-Tpm`, and Device Manager. The defaults announce IBM's software
TPM, which is a direct tell.

File:
[`VendorInfo.c`](https://github.com/stefanberger/libtpms/blob/master/src/tpm2/TPMCmd/Platform/src/VendorInfo.c)

```c
// In this sample platform, these are compile time constants, but are not required to be.
#define MANUFACTURER    "IBM"
#define VENDOR_STRING_1 "SW  "
#define VENDOR_STRING_2 " TPM"
#define VENDOR_STRING_3 "\0\0\0\0"
#define VENDOR_STRING_4 "\0\0\0\0"
#define FIRMWARE_V1     (0x20240125)
#define FIRMWARE_V2     (0x00120000)
#define MAX_SVN         255
```

```bash
git clone https://github.com/stefanberger/libtpms.git && cd libtpms
# edit src/tpm2/TPMCmd/Platform/src/VendorInfo.c
autoreconf -i && ./configure && make -j"$(nproc)"
```

### Layer 2: swtpm certificates

[swtpm](https://github.com/stefanberger/swtpm) issues the endorsement
key and platform certificates:

```bash
swtpm_setup \
  --tpmstate <dir> \
  --tpm2 \
  --create-ek-cert \
  --create-platform-cert \
  --lock-nvram
```

### Re-provisioning

The old identity is baked into persistent state. Delete the state
first, or the new vendor strings will not appear:

```bash
rm -rf <dir>/*; mkdir -p <dir>

swtpm_setup \
  --tpmstate <dir> \
  --tpm2 \
  --create-ek-cert \
  --create-platform-cert \
  --lock-nvram
```

### Verify from the Windows guest

```powershell
Get-Tpm

(Get-WmiObject -Namespace "root\cimv2\security\microsofttpm" -Class Win32_Tpm).ManufacturerIdTxt
```

Or open `tpm.msc` and read "TPM Manufacturer Information".

---

## 4. Linux kernel

[Kernel parameters](https://github.com/torvalds/linux/blob/master/Documentation/admin-guide/kernel-parameters.txt)

Each entry below is a value the guest can read to identify KVM. See
`RESEARCH.md` §4 for which ones our patch changes.

### CPUID hypervisor-present bit: `CPUID.1:ECX[31]`

Set in guest CPUID by
[`arch/x86/kvm/cpuid.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/cpuid.c).

### KVM CPUID signature and feature leaves

`KVMKVMKVM` at `0x40000000`, feature bits at `0x40000001`.

- Docs: [`cpuid.rst`](https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/cpuid.rst)
- Code: [`kvm_para.h`](https://github.com/torvalds/linux/blob/master/arch/x86/include/uapi/asm/kvm_para.h),
  [`cpuid.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/cpuid.c)

### KVM paravirtual MSRs

Range `0x4b564d00` to `0x4b564dff`, plus legacy `0x11` and `0x12`.

- Docs: [`msr.rst`](https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/msr.rst)
- Code: [`kvm_para.h`](https://github.com/torvalds/linux/blob/master/arch/x86/include/uapi/asm/kvm_para.h)

### `IA32_APERF` / `IA32_MPERF`

Controlled by `KVM_X86_DISABLE_EXITS_APERFMPERF`.

- Docs: [`api.rst`, KVM_CAP_X86_DISABLE_EXITS](https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/api.rst#713-kvm_cap_x86_disable_exits)
- UAPI flag: [`kvm.h`](https://github.com/torvalds/linux/blob/master/include/uapi/linux/kvm.h)
- Helper `kvm_aperfmperf_in_guest()`: [`x86.h`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/x86.h)
- VMX passthrough: [`vmx.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/vmx.c).
  Nested: [`nested.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/nested.c)
- SVM passthrough: [`svm.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/svm.c).
  Nested: [`nested.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/nested.c)
- Selftest: [`aperfmperf_test.c`](https://github.com/torvalds/linux/blob/master/tools/testing/selftests/kvm/x86/aperfmperf_test.c)

### KVM hypercall

`VMCALL` on Intel, `VMMCALL` on AMD.

- Docs: [`hypercalls.rst`](https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/hypercalls.rst)

Our patch deliberately leaves stock hypercall handling in place. See
`RESEARCH.md` §4, "Reverted (broke boot)", for what happens if you
force these to `#UD`.

### ACPI tables (host side)

`modules/qemu.sh` reads the host's own FADT at
`/sys/firmware/acpi/tables/FACP` to copy OEM ID, OEM table ID,
creator ID, and the preferred power-management profile into the
guest. A "Mobile" profile (value `2`) also triggers a search for a
battery SSDT to pass through. ACPI 6.6 §5.2.9 defines the table.
Section 5.2.9.1 lists the profile values.
