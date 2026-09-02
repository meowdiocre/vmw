# Firmware (EDK2 / OVMF)

`patches/EDK2/AMD-edk2-stable202605.patch` and
`patches/EDK2/Intel-edk2-stable202605.patch` change firmware identity
values. `steps/edk2.py` clones EDK2, applies the patch, builds OVMF,
and installs to `/opt/vmw/firmware/`.

See also: [MEASURED_BOOT](measured-boot.md), [BOOT_LOGO](boot-logo.md),
[identity strings](identity-strings.md).

## Build

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

The distro's `edk2-ovmf` package installs templates under
`/usr/share/edk2/x64/`. `steps/edk2.py` builds firmware from source
instead and installs it to `/opt/vmw/firmware/`, so the deployed
image carries the patched identity values.

## Boot logo BMP rules

The EDK2 image decoder rejects a logo that fails these checks, so
`steps/edk2.py` validates it before copying it in:

- Bytes `0`–`1` are `0x42 0x4D` (`BM`).
- Bit depth is `1`, `4`, `8`, or `24`.
- Compression is `0`.
- Width and height are 65535 or less.

Source:
[`GenC.py#L1892`](https://github.com/tianocore/edk2/blob/master/BaseTools/Source/Python/AutoGen/GenC.py#L1892)

## Secure Boot key enrollment

`build_ovmf()` in `steps/edk2.py` reads this host's own EFI keys
from `/sys/firmware/efi/efivars/`, writes them to JSON, and injects
them into a raw `.fd` with `virt-fw-vars --set-json`. This matches
the deployed firmware's Secure Boot keys to the host exactly.

Microsoft's published objects:
[secureboot_objects](https://github.com/microsoft/secureboot_objects).
`PreSignedObjects` holds PK/KEK/DB `.der` certificates.
`PostSignedObjects` holds
[`DBXUpdate.bin`](https://github.com/microsoft/secureboot_objects/blob/main/PostSignedObjects/DBX/amd64/DBXUpdate.bin).

EDK2's own enrollment app:
[`EnrollDefaultKeys`](https://github.com/tianocore/edk2/tree/master/OvmfPkg#readme)
(`OvmfPkg/EnrollDefaultKeys/EnrollDefaultKeys.{c,h,inf}`).

Tooling:
[UEFI variable store](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#uefi-variable-store),
[`virt-fw-vars` man page](https://man.archlinux.org/man/extra/virt-firmware/virt-fw-vars.1.en),
[`efijson.py`](https://gitlab.com/kraxel/virt-firmware/-/blob/master/virt/firmware/efi/efijson.py)

## "Last BIOS time: 0.0"

Task Manager reports a zero BIOS time because stock OVMF omits the
FPDT module. Add the FPDT DXE to the ACPI support section of
`OvmfPkg/OvmfPkgX64.dsc`:

```
MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.inf
```

Implementation:
`MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.c`.

## MOR / MORLock

Memory Overwrite Request control, expected on real Secure Boot
systems:

- [OvmfPkg README, line 160](https://github.com/tianocore/edk2/blob/master/OvmfPkg/README#L160)
- [`MemoryOverwriteControl`](https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteControl)
- [`MemoryOverwriteRequestControlLock`](https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteRequestControlLock)

## OVMF TPM support

- [`OvmfPkgX64.dsc#L39`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/OvmfPkgX64.dsc#L39)
- [`OvmfTpmDefines.dsc.inc`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Dsc/OvmfTpmDefines.dsc.inc)

## Boot order variable

`VMMBootOrderNNNN` (`L"BootOrder%04x"`) is built in
`OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c`.

## Specifications and GUIDs

- [UEFI specifications index](https://uefi.org/specifications)
- [ACPI 6.6](https://uefi.org/sites/default/files/resources/ACPI_Spec_6.6.pdf)
- [UEFI 2.11](https://uefi.org/sites/default/files/resources/UEFI_Spec_Final_2.11.pdf)

| Variable name | GUID |
|---|---|
| `EFI_GLOBAL_VARIABLE` | `8be4df61-93ca-11d2-aa0d-00e098032b8c` |
| `EFI_IMAGE_SECURITY_DATABASE_GUID` | `d719b2cb-3d3a-4596-a3bc-dad00e67656f` |

## Host paths

| What | Where |
|---|---|
| Writable NVRAM generated per domain | `/var/lib/libvirt/qemu/nvram` |
| Disk images | `/var/lib/libvirt/images/` |
| Built firmware | `/opt/vmw/firmware/` |
