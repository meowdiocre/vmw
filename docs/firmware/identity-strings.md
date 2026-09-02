# Identity strings

`patch_ovmf()` in `steps/edk2.py` rewrites firmware identity strings
with `sed`, using values read from the host. This keeps the firmware
and QEMU's own ACPI tables reporting the same identity instead of
disagreeing, and avoids shipping the stock `EDK II` vendor string,
which is readable from the guest through the EFI system table.

| PCD | Value | Source |
|---|---|---|
| `PcdFirmwareVendor` | `L"LENOVO"` | `/sys/class/dmi/id/bios_vendor` |
| `PcdFirmwareVersionString` | `L"HHCN23WW"` | `bios_version` |
| `PcdFirmwareReleaseDateString` | `L"11/08/2021"` | `bios_date` |
| `PcdFirmwareRevision` | `0x10017` | `bios_release` 1.23 |
| `PcdAcpiDefaultOemId` | `"LENOVO"` | FADT offset 10, 6 bytes |
| `PcdAcpiDefaultOemTableId` | `0x20202031302d4243` | FADT offset 16 (`CB-01   `) |
| `PcdAcpiDefaultOemRevision` | `0x1` | FADT offset 24 |
| `PcdAcpiDefaultCreatorId` | `0x49504341` | FADT offset 28 (`ACPI`) |
| `PcdAcpiDefaultCreatorRevision` | `0x40000` | FADT offset 32 |

`steps/qemu.py` writes the same OEM ID and table ID into QEMU's
`aml-build.c`, so the firmware and the emulator report one identity.

## `PcdAcpiDefaultOemId` quoting

The `sed` substitution matches `"INTEL "` including its quotes and
must put the replacement back with quotes, since the field is a
`VOID*` PCD:

```sed
s@(PcdAcpiDefaultOemId)\|"INTEL "\|@\1|"'"$OEMID"'"|@
```

`patch_ovmf()` also refuses to run when the host FADT read returns
nothing or the OEM ID is not exactly 6 bytes, rather than writing an
empty value into the firmware.
