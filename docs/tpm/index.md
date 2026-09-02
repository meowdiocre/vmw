# TPM (libtpms / swtpm)

TPM identity comes from two layers. Both must change, or the guest
sees a mismatch between them.

## Layer 1: libtpms runtime identity

This is what Windows reads through `TPM2_GetCapability`: `tpm.msc`,
`Get-Tpm`, and Device Manager. The defaults announce IBM's software
TPM, a direct tell.

File:
[`VendorInfo.c`](https://github.com/stefanberger/libtpms/blob/master/src/tpm2/TPMCmd/Platform/src/VendorInfo.c)

```c
#define MANUFACTURER    "IBM"
#define VENDOR_STRING_1 "SW  "
#define VENDOR_STRING_2 " TPM"
#define FIRMWARE_V1     (0x20240125)
#define FIRMWARE_V2     (0x00120000)
```

Build with the vendor strings changed:

```bash
git clone https://github.com/stefanberger/libtpms.git && cd libtpms
# edit src/tpm2/TPMCmd/Platform/src/VendorInfo.c
autoreconf -i && ./configure && make -j"$(nproc)"
```

## Layer 2: swtpm certificates

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

## Re-provisioning

TPM identity is baked into persistent state at first setup. Delete
the state directory before re-running `swtpm_setup`, or the new
vendor strings will not appear:

```bash
rm -rf <dir>/*; mkdir -p <dir>

swtpm_setup \
  --tpmstate <dir> \
  --tpm2 \
  --create-ek-cert \
  --create-platform-cert \
  --lock-nvram
```

## Verify from the guest

```powershell
Get-Tpm
(Get-WmiObject -Namespace "root\cimv2\security\microsofttpm" -Class Win32_Tpm).ManufacturerIdTxt
```

Or open `tpm.msc` and read "TPM Manufacturer Information".
