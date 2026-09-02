# MEASURED_BOOT

VMAware reads the TBS TCG log for event
`EV_EFI_PLATFORM_FIRMWARE_BLOB` (event `0x80000008`, PCR 0) and
compares it against OVMF's known firmware-volume bounds. The check is
an exact match on the base address and length pair
(`vmaware.hpp`, `measured_boot()`):

```c
if ((base_addr == 0x830000 && blob_len == 0xD0000) ||   /* PEIFV */
    (base_addr == 0x900000 && blob_len == 0xE80000)) {  /* DXEFV */
    return true;
}
```

Both branches test the base address only, so moving either volume
defeats the match.

## Fix

`patches/EDK2/AMD-edk2-stable202605.patch` moves
`MEMFD_BASE_ADDRESS` from `0x800000` to `0x820000` in
`OvmfPkg/Include/Fdf/OvmfPkgDefines.fdf.inc`. Every volume inside
MEMFD sits at a fixed offset from that base
(`OvmfPkg/Include/Fdf/MemFd.fdf.inc`: PEIFV at `+0x030000`, DXEFV at
`+0x100000`), so one define moves both.

| PCD | Value | VMAware expects |
|---|---|---|
| `PcdOvmfPeiMemFvBase` | `0x850000` | `0x830000` — no match |
| `PcdOvmfPeiMemFvSize` | `0x0D0000` | `0x0D0000` |
| `PcdOvmfDxeMemFvBase` | `0x920000` | `0x900000` — no match |
| `PcdOvmfDxeMemFvSize` | `0xE80000` | `0xE80000` |

Only `OVMF_CODE.fd` changes. `OVMF_VARS.fd` (the variable store) does
not depend on `MEMFD_BASE_ADDRESS`, so a rebuild produces a
byte-identical variable store and any enrolled Secure Boot keys or
per-domain NVRAM stay valid.

## Rollback

The pre-change firmware is kept at
`/opt/vmw/firmware/OVMF_CODE.fd.pre-memfd.bak`:

```bash
cp /opt/vmw/firmware/OVMF_CODE.fd.pre-memfd.bak \
   /opt/vmw/firmware/OVMF_CODE.fd
```

## Applying a firmware change

pflash images load at domain start. A reboot from inside the guest
keeps the old firmware; the domain must be stopped and started for a
firmware change to take effect. Confirm the running QEMU process has
picked up the new image by checking its open file handles:

```bash
ls -l /proc/<pid>/fd | grep OVMF_CODE
```

If a firmware change trips a BitLocker recovery prompt, suspend
protection for one boot from inside the guest first:

```powershell
manage-bde -status C:
manage-bde -protectors -disable C: -RebootCount 1
```
