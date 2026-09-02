# BOOT_LOGO

VMAware hashes the guest's boot logo and compares it against two
known constants:

```c
switch (hash) {
    case 0x110350C5: return core::add(brand_enum::QEMU);   /* TianoCore EDK2 */
    case 0x87c39681: return core::add(brand_enum::HYPERV);
    default:         return false;
}
```

## Fix

`steps/edk2.py` replaces `MdeModulePkg/Logo/Logo.bmp` with the
host's BGRT image (`/sys/firmware/acpi/bgrt/image`) before the build.
The host BGRT passes EDK2's decoder rules (see
[Firmware: boot logo BMP rules](index.md#boot-logo-bmp-rules)): 505×98,
24 bpp, uncompressed.

## The hash is not taken over the file

Windows does not return `Logo.bmp` directly.
`NtQuerySystemInformation` (`SystemBootLogoInformation`, class 140)
returns the BGRT bitmap that OVMF re-encodes from `Logo.bmp` at boot,
at different dimensions and colour depth than the source file. The
resulting hash cannot be predicted from the source bitmap; a logo
change is confirmed by booting and re-running VMAware, not by
hashing the file.
