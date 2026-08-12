# QEMU (Emulator)

<details>
<summary>Expand for details...</summary>

## KVM-specific Custom MSR/Signatures

> Reference(s): [`kvm_para.h`](https://gitlab.com/qemu-project/qemu/-/blob/master/include/standard-headers/asm-x86/kvm_para.h)

## Hypervisor Bit

Clears `CPUID.1.ECX[31]` - the universal "hypervisor present" indicator.

```bash
qemu-system-x86_64 -cpu host,-hypervisor
```
```xml
  <cpu>
    <feature policy="disable" name="hypervisor"/>
  </cpu>
```

## KVM Signature & Feature Bits

Hides `CPUID 0x40000000` (`KVMKVMKVM` signature) and `CPUID 0x40000001` (KVM feature bits).

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

## KVM PV Enforce CPUID

> Reference(s): [`kvm.c`](https://github.com/qemu/qemu/raw/refs/heads/master/target/i386/kvm/kvm.c)
> [`kvm-pv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/kvm-pv.rst)
> [`#GP`](https://en.wikipedia.org/wiki/General_protection_fault)

When enabled, QEMU sets the `kvm_pv_enforce_cpuid` property, which triggers `target/i386/kvm/kvm.c` to issue `kvm_vcpu_enable_cap` with `KVM_CAP_ENFORCE_PV_FEATURE_CPUID`. 

This forces KVM to strictly enforce paravirtual CPUID feature advertisement. If the guest attempts to access a KVM PV MSR (range `0x4b564d00-08`) corresponding to a feature that was not explicitly advertised in the KVM CPUID leaf (`0x40000001`), KVM will inject a `#GP` (General Protection Fault) into the guest. This ensures the guest OS cannot interact with or utilize unrequested paravirtual optimizations.

```bash
qemu-system-x86_64 -cpu host,kvm-pv-enforce-cpuid=on
```

```xml
<qemu:commandline>
  <qemu:arg value='-cpu'/>
  <qemu:arg value='host,kvm-pv-enforce-cpuid=on'/>
</qemu:commandline>
```

## Hyper-V Enlightenments

> Reference: [`hyperv.rst`](https://github.com/qemu/qemu/blob/master/docs/system/i386/hyperv.rst)

</details>








---









# EDK2 (OVMF)

<details>
<summary>Expand for details...</summary>





- https://github.com/tianocore/tianocore.github.io/wiki/Common-instructions
- https://github.com/tianocore/tianocore.github.io/wiki/How-to-build-OVMF
- https://github.com/tianocore/edk2/tree/master/OvmfPkg

## NVRAM Template:

```
sudo pacman -S edk2-ovmf
```

```
/usr/share/edk2/x64/MICROVM.4m.fd
/usr/share/edk2/x64/OVMF.4m.fd
/usr/share/edk2/x64/OVMF_CODE.4m.fd
/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd
/usr/share/edk2/x64/OVMF_VARS.4m.fd
```

## BmpImageDecoder (BMP Validator)
- https://github.com/tianocore/edk2/blob/master/BaseTools/Source/Python/AutoGen/GenC.py#L1892
  - File Type: Bytes `0–1` must be `0x42 0x4D`
  - Bit Depth: Must be `1`, `4`, `8`, or `24`
  - Compression: Must be `0`
  - Width/Height: `≤65535x65535`




## VMMBootOrderNNNN (L"BootOrder%04x")
- OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c






## OVMF PK/KEK Vendor String & EnrollDefaultKeys
- EnrollDefaultKeys
  - https://github.com/tianocore/edk2/tree/master/OvmfPkg#readme
  - OvmfPkg/EnrollDefaultKeys/EnrollDefaultKeys.c
  - OvmfPkg/EnrollDefaultKeys/EnrollDefaultKeys.h
  - OvmfPkg/EnrollDefaultKeys/EnrollDefaultKeys.inf
- OvmfPkg/OvmfPkg.dec
- OvmfPkg/Include/Guid/OvmfPkKek1AppPrefix.h





## Old script for reference
```bash
################################################################################
# Compile OVMF and inject Secure Boot certs into template VARS
################################################################################
compile_and_inject_ovmf() {
  local WORKSPACE EDK_TOOLS_PATH CONF_PATH TEMP_DIR URL UUID

  fmtr::info "Configuring build environment..."

  export WORKSPACE="$(pwd)"
  export EDK_TOOLS_PATH="$WORKSPACE/BaseTools"
  export CONF_PATH="$WORKSPACE/Conf"

  [ -d BaseTools/Build ] || { make -C BaseTools -j"$(nproc)" && source edksetup.sh; } &>>"$LOG_FILE" || { fmtr::fatal "Failed to build BaseTools"; return 1; }

  build -a X64 -p OvmfPkg/OvmfPkgX64.dsc -b RELEASE -t GCC -n 0 -s \
    --define SECURE_BOOT_ENABLE=TRUE \
    --define TPM1_ENABLE=TRUE \
    --define TPM2_ENABLE=TRUE \
    --define SMM_REQUIRE=TRUE &>>"$LOG_FILE" || { fmtr::fatal "Failed to build OVMF"; return 1; }

  $ROOT_ESC mkdir -p "$OUT_DIR/firmware"

  for f in CODE VARS; do
    $ROOT_ESC "$OUT_DIR/emulator/bin/qemu-img" convert -f raw -O qcow2 "Build/OvmfX64/RELEASE_GCC/FV/OVMF_${f}.fd" "$OUT_DIR/firmware/OVMF_${f}.qcow2" || return 1
  done

  TEMP_DIR="$(mktemp -d)" || return 1
  trap 'rm -rf "$TEMP_DIR"' RETURN

  URL="https://raw.githubusercontent.com/microsoft/secureboot_objects/main"
  UUID="77fa9abd-0359-4d32-bd60-28f4e78f784b"

  local -A certs=(
    # PK (Platform Key)
    ["ms_pk_oem.der"]="$URL/PreSignedObjects/PK/Certificate/WindowsOEMDevicesPK.der"
    # KEK (Key Exchange Key)
    ["ms_kek_2011.der"]="$URL/PreSignedObjects/KEK/Certificates/MicCorKEKCA2011_2011-06-24.der"
    ["ms_kek_2023.der"]="$URL/PreSignedObjects/KEK/Certificates/microsoft%20corporation%20kek%202k%20ca%202023.der"
    # DB (Signature Database)
    ["ms_db_uefi_2011.der"]="$URL/PreSignedObjects/DB/Certificates/MicCorUEFCA2011_2011-06-27.der"
    ["ms_db_pro_2011.der"]="$URL/PreSignedObjects/DB/Certificates/MicWinProPCA2011_2011-10-19.der"
    ["ms_db_optionrom_2023.der"]="$URL/PreSignedObjects/DB/Certificates/microsoft%20option%20rom%20uefi%20ca%202023.der"
    ["ms_db_uefi_2023.der"]="$URL/PreSignedObjects/DB/Certificates/microsoft%20uefi%20ca%202023.der"
    ["ms_db_windows_2023.der"]="$URL/PreSignedObjects/DB/Certificates/windows%20uefi%20ca%202023.der"
    # DBX (Forbidden Signatures Database)
    ["dbxupdate.bin"]="$URL/PostSignedObjects/DBX/amd64/DBXUpdate.bin"
  )

  for c in "${!certs[@]}"; do
    wget -q -O "$TEMP_DIR/$c" "${certs[$c]}" &
  done
  wait || { fmtr::fatal "Failed to download one or more certificates"; return 1; }

  # Generate efivars.json
  local efivars_json="$TEMP_DIR/efivars.json"
  local -A guids=(
    ["dbDefault"]="8be4df61-93ca-11d2-aa0d-00e098032b8c"
    ["dbxDefault"]="8be4df61-93ca-11d2-aa0d-00e098032b8c"
    ["KEKDefault"]="8be4df61-93ca-11d2-aa0d-00e098032b8c"
    ["PKDefault"]="8be4df61-93ca-11d2-aa0d-00e098032b8c"
  )

  {
    local entries=() var path hex attr data entry

    for var in "${!guids[@]}"; do
      path="/sys/firmware/efi/efivars/${var}-${guids[$var]}"
      [[ -f "$path" ]] || continue

      hex=$(hexdump -ve '1/1 "%.2x"' "$path" 2>/dev/null)
      [[ ${#hex} -ge 8 ]] || continue

      # Parse attribute (little-endian 4 bytes) and data
      attr=$(( 16#${hex:6:2}${hex:4:2}${hex:2:2}${hex:0:2} ))
      data=${hex:8}

      # Build JSON entry
      entry=$(printf '        {
              "name": "%s",
              "guid": "%s",
              "attr": %d,' "$var" "${guids[$var]}" "$attr")

      # Handle EFI_VARIABLE_TIME_BASED_AUTHENTICATED_WRITE_ACCESS (0x20)
      if (( attr & 0x20 )) && [[ ${#data} -ge 32 ]]; then
        entry+=$(printf '
              "data": "%s",
              "time": "%s"
          }' "${data:32}" "${data:0:32}")
      else
        entry+=$(printf '
              "data": "%s"
          }' "$data")
      fi

      entries+=("$entry")
    done

    # Output complete JSON
    printf '{\n    "version": 2,\n    "variables": [\n'
    local IFS=','$'\n'
    echo "${entries[*]}"
    printf '    ]\n}\n'
  } > "$efivars_json"

  $ROOT_ESC virt-fw-vars --input "$OUT_DIR/firmware/OVMF_VARS.qcow2" --output "$OUT_DIR/firmware/OVMF_VARS.qcow2" \
    --secure-boot \
    --set-pk "$UUID" "$TEMP_DIR/ms_pk_oem.der" \
    --add-kek "$UUID" "$TEMP_DIR/ms_kek_2011.der" \
    --add-kek "$UUID" "$TEMP_DIR/ms_kek_2023.der" \
    --add-db "$UUID" "$TEMP_DIR/ms_db_uefi_2011.der" \
    --add-db "$UUID" "$TEMP_DIR/ms_db_pro_2011.der" \
    --add-db "$UUID" "$TEMP_DIR/ms_db_optionrom_2023.der" \
    --add-db "$UUID" "$TEMP_DIR/ms_db_uefi_2023.der" \
    --add-db "$UUID" "$TEMP_DIR/ms_db_windows_2023.der" \
    --set-dbx "$TEMP_DIR/dbxupdate.bin" \
    --set-json "$efivars_json" &>>"$LOG_FILE" || { fmtr::fatal "Failed to inject"; return 1; }
}
```





## OVMF MOR/MORLock support:
- https://github.com/tianocore/edk2/blob/master/OvmfPkg/README#L160
- https://github.com/tianocore/tianocore.github.io/wiki/How-to-Enable-Security
- https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteControl
- https://github.com/tianocore/edk2/tree/master/SecurityPkg/Tcg/MemoryOverwriteRequestControlLock
- https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Dsc/MorLock.dsc.inc
- https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Fdf/MorLock.fdf.inc

## OVMF TPM support:
- https://github.com/tianocore/edk2/blob/master/OvmfPkg/OvmfPkgX64.dsc#L39
- https://github.com/tianocore/edk2/blob/master/OvmfPkg/Include/Dsc/OvmfTpmDefines.dsc.inc

OVMF Build Args:
```
build -a X64 -p OvmfPkg/OvmfPkgX64.dsc -b RELEASE -t GCC -n 0 -s \
  --define SECURE_BOOT_ENABLE=TRUE \
  --define SMM_REQUIRE=TRUE \
  --define TPM1_ENABLE=TRUE \
  --define TPM2_ENABLE=TRUE \
```

QEMU XML:
```xml
  <features>
    <smm state="on"/>
  </features>
...
    <tpm model="tpm-crb">
      <backend type="emulator" version="2.0"/>
    </tpm>
```

## Last BIOS time: 0.0
#### Add FPDT module to OVMF
- ```MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.c```
- ```OvmfPkg/OvmfPkgX64.dsc```
```
  #
  # ACPI Support
  #
  MdeModulePkg/Universal/Acpi/AcpiTableDxe/AcpiTableDxe.inf
  OvmfPkg/AcpiPlatformDxe/AcpiPlatformDxe.inf
!if $(STANDALONE_MM_ENABLE) != TRUE
  MdeModulePkg/Universal/Acpi/S3SaveStateDxe/S3SaveStateDxe.inf
  MdeModulePkg/Universal/Acpi/BootScriptExecutorDxe/BootScriptExecutorDxe.inf
!endif
  MdeModulePkg/Universal/Acpi/BootGraphicsResourceTableDxe/BootGraphicsResourceTableDxe.inf
  MdeModulePkg/Universal/Acpi/FirmwarePerformanceDataTableDxe/FirmwarePerformanceDxe.inf     <---- Add
```
- ```OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c```
  - Search for function: `GetFrontPageTimeoutFromQemu`

## Secure Boot

- [https://github.com/microsoft/secureboot_objects](https://github.com/microsoft/secureboot_objects)
  - PostSignedObjects
    - [DBXUpdate.bin](https://github.com/microsoft/secureboot_objects/blob/main/PostSignedObjects/DBX/amd64/DBXUpdate.bin)
  - PreSignedObjects
    - [PK,KEK,DB.der](https://github.com/microsoft/secureboot_objects/blob/main/PreSignedObjects)

## virt-fw-vars
- [uefi-variable-store](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#uefi-variable-store)
- [virt-fw-vars - man page](https://man.archlinux.org/man/extra/virt-firmware/virt-fw-vars.1.en)
- [json support for efi - python script](https://gitlab.com/kraxel/virt-firmware/-/blob/master/virt/firmware/efi/efijson.py)

## Generated firmware from template that is writable:

```
/var/lib/libvirt/qemu/nvram
```

## STORAGE:

```
/var/lib/libvirt/images/
```



## Firmware Specifications

- https://uefi.org/specifications
  - [ACPI Specification](https://uefi.org/sites/default/files/resources/ACPI_Spec_6.6.pdf)
  - [UEFI Specification](https://uefi.org/sites/default/files/resources/UEFI_Spec_Final_2.11.pdf)

| Variable Name | Variable GUID |
|-|-|
| EFI_GLOBAL_VARIABLE | 8be4df61-93ca-11d2-aa0d-00e098032b8c |
| EFI_IMAGE_SECURITY_DATABASE_GUID | d719b2cb-3d3a-4596-a3bc-dad00e67656f |





</details>








---
















# libtpms/swtpm (TPM)

<details>
<summary>Expand for details...</summary>

- https://github.com/stefanberger/libtpms

## Layer 1: libtpms (Runtime Identity)

> What Windows reads via `TPM2_GetCapability` (`tpm.msc`, `Get-Tpm`, Device Manager)

- [src/tpm2/TPMCmd/Platform/src/VendorInfo.c](https://github.com/stefanberger/libtpms/blob/master/src/tpm2/TPMCmd/Platform/src/VendorInfo.c)

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
```
- Edit src/tpm2/TPMCmd/Platform/src/VendorInfo.c
```bash
autoreconf -i && ./configure && make -j"$(nproc)"
```

## Layer 2: swtpm Certificates (EK & Platform certs)

- https://github.com/stefanberger/swtpm

```bash
swtpm_setup \
  --tpmstate <dir> \
  --tpm2 \
  --create-ek-cert \
  --create-platform-cert \
  --lock-nvram
```

## Re-provision TPM State

> ⚠️ Delete existing TPM state first - old identity is baked into persistent state.

```bash
rm -rf <dir>/*; mkdir -p <dir>

swtpm_setup \
  --tpmstate <dir> \
  --tpm2 \
  --create-ek-cert \
  --create-platform-cert \
  --lock-nvram
```

## Verify (Windows Guest)

```powershell
Get-Tpm

(Get-WmiObject -Namespace "root\cimv2\security\microsofttpm" -Class Win32_Tpm).ManufacturerIdTxt
```

Or open `tpm.msc` → "TPM Manufacturer Information"

</details>


















---








# Linux (Kernel)

<details>
<summary>Expand for details...</summary>

---

- Kernel Paramaters:
  - https://github.com/torvalds/linux/blob/master/Documentation/admin-guide/kernel-parameters.txt

---

- CPUID hypervisor-present bit (`CPUID.1:ECX[31]`)
  - Code (set in guest CPUID):
    - https://github.com/torvalds/linux/blob/master/arch/x86/kvm/cpuid.c

---

- KVM CPUID signature leaf (`KVMKVMKVM` at `0x40000000`) and feature leaf (`0x40000001`)
  - Documentation:
    - https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/cpuid.rst
  - Code:
    - https://github.com/torvalds/linux/blob/master/arch/x86/include/uapi/asm/kvm_para.h
    - https://github.com/torvalds/linux/blob/master/arch/x86/kvm/cpuid.c

---

- KVM-specific MSRs (paravirt MSR range `0x4b564d00`–`0x4b564dff`, plus legacy `0x11`/`0x12`)
  - Documentation:
    - https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/msr.rst
  - Code:
    - https://github.com/torvalds/linux/blob/master/arch/x86/include/uapi/asm/kvm_para.h

---

- `IA32_APERF` and `IA32_MPERF` MSRs (`KVM_X86_DISABLE_EXITS_APERFMPERF`) 
  - Documentation:
    - https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/api.rst#713-kvm_cap_x86_disable_exits
  - Code:
    - UAPI flag: https://github.com/torvalds/linux/blob/master/include/uapi/linux/kvm.h
    - Helper `kvm_aperfmperf_in_guest()`: https://github.com/torvalds/linux/blob/master/arch/x86/kvm/x86.h
    - Intel/VMX passthrough: https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/vmx.c
    - Intel/VMX nested: https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/nested.c
    - AMD/SVM passthrough: https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/svm.c
    - AMD/SVM nested: https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/nested.c
    - Selftest: https://github.com/torvalds/linux/blob/master/tools/testing/selftests/kvm/x86/aperfmperf_test.c

---

- KVM Hypercall (`VMCALL` on Intel / `VMMCALL` on AMD)
  - Documentation:
    - https://github.com/torvalds/linux/blob/master/Documentation/virt/kvm/x86/hypercalls.rst

---

</details>











---













# Looking Glass

<details>
<summary>Expand for details...</summary>

- https://looking-glass.io/
- https://github.com/gnif/LookingGlass

- Building
  - https://looking-glass.io/docs/B7/build/#building-the-windows-installer

## Unique Identifiers:

- GUID
  - vendor/ivshmem/ivshmem.h
- Windows driver/package
  - host/platform/Windows/installer.nsi
  - idd/installer.nsi
- Vendor/Device IDs
  - module/kvmfr.c

#### GUID_DEVINTERFACE_IVSHMEM
```
LookingGlass/vendor/ivshmem/ivshmem.h
```
```h
DEFINE_GUID (GUID_DEVINTERFACE_IVSHMEM,
    0xdf576976,0x569d,0x4672,0x95,0xa0,0xf5,0x7e,0x4e,0xa0,0xb2,0x10);
// {df576976-569d-4672-95a0-f57e4ea0b210}
```

#### Windows Driver Interface GUID
```
idd/LGIdd/Public.h
```
```h
// {997b0b66-b74c-4017-9a89-e4aad41d3780}
DEFINE_GUID (GUID_DEVINTERFACE_LGIdd, 0x997b0b66,0xb74c,0x4017,0x9a,0x89,0xe4,0xaa,0xd4,0x1d,0x37,0x80);
```

#### Driver Tracing GUID
```
idd/LGIdd/Trace.h
```
```h
  WPP_DEFINE_CONTROL_GUID(                                      \
    MyDriver1TraceGuid, (58bf0aac,4a52,4560,9873,693b645c0a47), \
```

#### Hardware ID and Registry Key
```
idd/LGIddInstall/LGIddInstall.c
```
```
#define LGIDD_CLASS_GUID GUID_DEVCLASS_DISPLAY
#define LGIDD_CLASS_NAME L"Display"
#define LGIDD_HWID L"Root\\LGIdd"
#define LGIDD_HWID_MULTI_SZ (LGIDD_HWID "\0")
#define LGIDD_INF_NAME L"LGIdd.inf"
#define LGIDD_REGKEY L"Software\\LookingGlass\\IDD"
```

#### KVMFR Protocol Magic & Version
```
common/include/common/KVMFR.h
```
```
#define KVMFR_MAGIC   "KVMFR---"
#define KVMFR_VERSION 20
```

#### PCI_KVMFR_{VENDOR,DEVICE}_ID
```
module/kvmfr.c
```
```c
#define PCI_KVMFR_VENDOR_ID 0x1af4 //Red Hat Inc,
#define PCI_KVMFR_DEVICE_ID 0x1110 //Inter-VM shared memory
...
#define KVMFR_DEV_NAME    "kvmfr"
```

</details>
