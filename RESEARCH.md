# VMW Research Notes: VM-Detection Study

This document holds the research findings behind this workspace: why
the patches in `patches/` exist, what each one fixes, what we tried
and rejected, and what is still open. `README.md` explains how to run
the tool. This file explains why the tool builds what it builds.

---

## 1. Goal

We run Windows 10 as a guest under KVM and study how VMAware, a
VM-detection library, sees the guest. We have three goals, and the
first two pull against each other:

1. **Beat VMAware's checks.** Find each detection and remove it.
2. **Keep nested virtualization real.** The guest must run Hyper-V
   with HVCI (Memory Integrity) turned on, and nested WHP partitions
   inside the guest must work. Our VBS/HVCI research needs this.
3. **Keep GPU passthrough working.** The guest must see the RTX
   3050 Ti with WDDM and no Code 43, for benchmarking.

A guest with no hypervisor exposed passes more VMAware checks, but it
cannot run Hyper-V or HVCI. Turning Hyper-V on exposes a hypervisor
layer, and some checks come back. We keep Hyper-V and HVCI on and
clean up what that turns on.

### Terms used below

- **Host / L0**: this machine's patched kernel, the KVM host.
- **Guest / L1**: the Windows 10 VM. Hyper-V's own hypervisor,
  `hvix64`, runs inside this guest as its root partition manager.
- **L2**: a partition that `hvix64` creates inside the guest. It is
  either the normal Windows root partition, or a throwaway partition
  an app builds through the WHP API (`WHvCreatePartition`).

---

## 2. Where the research lives in this repo

| Piece | Path | What it holds |
|---|---|---|
| Kernel patch | `patches/Kernel/amd702.mypatch` | Every host-side change described in §4 |
| QEMU patch | `patches/QEMU/AMD-v11.0.3.patch` | Device-model identity changes, ACPI tables |
| ACPI tables | `patches/QEMU/fake_battery.aml`, `spoofed_devices.aml` | Injected via QEMU, source `.dsl` alongside |
| EDK2/OVMF patch | `patches/EDK2/AMD-edk2-stable202605.patch` | Firmware identity changes; still needs the MEMFD fix in §6 |
| Kernel build driver | `modules/kernel.sh` | Clones `linux-tkg`, stages the patch, builds |
| QEMU build driver | `modules/qemu.sh` | Clones QEMU, applies the patch, builds, rewrites SMBIOS/ACPI |
| EDK2 build driver | `modules/edk2.sh` | Clones EDK2, applies the patch, builds OVMF |
| VM profile | `configs/aptwannabe.yml` | The `aptwannabe` domain: CPU topology, Hyper-V block, clock, devices |
| Patch integrity | `python/vmw/patches.py`, `patches/checksums.sha256` | SHA256 + target-version check, run by `vmw patch-status` |
| Patch-vs-source check | `python/vmw/patchcheck.py` | Clones the real upstream tag and dry-runs `git apply --check` |
| VMAware source | `../VMAware/src/vmaware.hpp` | The detector we are studying (outside this repo) |

Run `vmw patch-status` before a build. It confirms the patch files
match `checksums.sha256`. Run `vmw patch-check kernel` to confirm the
kernel patch still applies cleanly to a fresh source tree before you
spend an hour building.

---

## 3. Current state

Host kernel `7.0.0-273-tkg-eevdf` (built from this repo) runs the VM
`aptwannabe` with 8 vCPUs (4 cores x 2 threads), 8 GiB of hugepages,
Hyper-V and HVCI turned on in the guest, and the RTX 3050 Ti passed
through with no Code 43.

The last measured run reported **2 detections out of 85 checks**:

- **MEASURED_BOOT**: fixed on 2026-08-28. New firmware is built,
  installed, and the guest is now running on it. VMAware has not been
  re-run inside the guest yet, so the count above is still the old
  measurement (§6).
- **TIMER**, memory-ratio half only: not fixable by speeding up the
  existing code path. See §7 for why, and for the one real option
  left.

Every other check passes, including the HYPERV_HOST classification.
VMAware correctly sees a root Hyper-V partition. That classification
raises its TIMER threshold and runs its nested-hypervisor checks.
This is the harder path, and we pass it everywhere except the memory
ratio.

Some commands below need root. Export the dev box password once per
shell (`read -rs VMW_SUDO`) and pipe it, rather than putting it in a
file: `echo "$VMW_SUDO" | sudo -S <cmd>`. Do not use `sudo -A`; it
opens a graphical prompt.

---

## 4. The kernel patch (`patches/Kernel/amd702.mypatch`)

Eight files change: `arch/x86/kvm/{cpuid.c, emulate.c, x86.c,
hyperv.c, svm/svm.c, svm/nested.c, svm/svm.h}`, and
`include/linux/percpu.h`.

**Regeneration rule.** The patch is built by copying every changed
file into a pristine clone under `.vmw/patchcheck/kernel/v7.0` and
running `git diff`. Copy **all eight** files every time, even the
ones you did not touch this round. Copying only the files you just
edited drops old hunks silently. This is exactly how the
KVM_INTERCEPTION check came back once: a regeneration copied
`svm.c`, `nested.c`, `svm.h`, and `percpu.h` but skipped `cpuid.c`,
`emulate.c`, and `x86.c`, and their fixes vanished from the patch.

### What each part does

- **percpu allocation.** `PERCPU_MODULE_RESERVE` goes from 8 KB to
  32 KB in `include/linux/percpu.h`. `kvm_amd` needs 7280 bytes of
  percpu space and failed to load on every boot without this fix
  ("Could not allocate 7280 bytes percpu data" leads to no
  `/dev/kvm`, and libvirt then refuses to define the domain). Keep
  this fix; it is not optional.

- **CPUID cache.** `handle_cpuid` gets a per-CPU cache
  (`VMW_CPUID_CACHE_ENTRIES=256`) so repeated `(leaf, subleaf)`
  lookups skip `kvm_emulate_cpuid`.

- **VMCALL/VMMCALL stop emulating on `#UD`.** `EmulateOnUD` is
  removed from the VMCALL and VMMCALL opcode entries in `emulate.c`.
  These instructions now raise a clean `#UD` instead of being
  emulated after an interception. This is what fixes VMAware's
  KVM_INTERCEPTION check: it flags ACCESS_VIOLATION when it sees KVM
  patching instructions live. **Do not go further and make
  VMCALL/VMMCALL return `#UD` unconditionally.** That was tried; see
  the "Reverted" list below.

- **P-state / CPPC MSR passthrough.** MSRs `0xc0010062` through
  `0xc001006b`, plus `0xc0010293`, `0xc001029a`, and `0xc00102b0`
  through `0xc00102b3`, read through `rdmsr_safe` in
  `kvm_get_msr_common`. This is the CPU-Z "max multiplier" fix. The
  same ranges accept writes silently in `kvm_set_msr_common`. `svm.c`
  turns off read interception for the same ranges.

- **CPUID leaf 7 mask.** `entry->edx &= 0x73FFFFFF;` runs after the
  leaf-7 EDX override. It masks AMD-reserved hypervisor bits.

- **MCE gate removal.** `x86.c` drops the `MCG_CTL_P` and
  `MCG_CMCI_P` checks in `set_msr_mce` and `get_msr_mce`. It also
  comments out the XSS read/write gates (for XSAVES).

- **Hypercall quirk.** `svm_vm_init` sets
  `disabled_quirks |= KVM_X86_QUIRK_FIX_HYPERCALL_INSN`.

- **Native intercepts cleared.** RDTSC/RDTSCP, RDPMC, INVD, INVLPGA,
  TASK_SWITCH, WBINVD, RDPRU, VMLOAD/VMSAVE/STGI/CLGI/SKINIT.

- **`#GP` intercept + CPL3 `#UD`.** `set_exception_intercept` turns
  on `GP_VECTOR` unconditionally in `init_vmcb`.
  `gp_interception` turns a CPL3 SVM-instruction fault into `#UD`.
  This fixes VMAware's SVM_EXCEPTIONS check: bare metal returns `#UD`
  for `VMLOAD` at CPL3, and before this fix KVM did not.

- **L2 CPUID track + patch.** `svm_vmw_track_l2_cpuid()`, called from
  the nested branch of `svm_handle_exit`, records the L2 CPUID leaf
  (`kvm_rax_read`) and the exit RIP (`vmcb->save.rip`), then forwards
  the exit to the guest (`hvix64`) untouched.
  `svm_vmw_patch_l2_cpuid_answer(vcpu, vmcb12)`, called from
  `nested_svm_vmrun()` right after `nested_copy_vmcb_save_to_cache()`,
  waits for L2 to resume at `exit_rip + 2` and then patches only the
  detection-relevant bits of the answer:

  - Leaf `0x40000000`: RBX/RCX/RDX become `"Micr"`/`"osof"`/`"t Hv"`.
  - Leaf `0x40000003`: RBX gets the root-partition bit (`| 1`).
  - Leaf `0x40000006`: RAX clears bits `0x3c00`.

  SVM's VMRUN only loads RAX/RSP/RIP from the VMCB. RBX/RCX/RDX have
  to reach L2 through `vcpu->arch.regs`. The patch writes both
  `vmcb12` and `regs`.

  **Never answer L2 CPUID directly with fabricated values.** The
  Windows secure kernel needs the real 128-bit privilege mask from
  `hvix64`'s own leaf `0x40000003`. Faking that mask broke VBS/HVCI
  init outright: the guest hung at boot with CPU0 halted in the
  kernel, every vCPU idle, and no DHCP lease. Track the real answer
  and patch only the specific bits that VMAware reads.

- **L2 CPUID fastpath.** `svm_vmw_answer_l2_cpuid_fastpath()`, called
  from `svm_exit_handlers_fastpath`, answers repeated L2 CPUID from a
  per-vCPU cache of `hvix64`'s own previous answers. It serves leaf
  0 and the Hyper-V leaf range only. It returns
  `EXIT_FASTPATH_REENTER_GUEST`, an IRQs-off re-entry that skips the
  full exit path. The cache is filled by
  `svm_vmw_patch_l2_cpuid_answer` (32 entries, keyed on
  leaf+subleaf). The slow path stays in `svm_handle_exit` as a
  fallback. This is what fixed VMAware's TIMER instruction-ratio: it
  dropped from 155 to about 11.4 against a 15.0 threshold, because
  cached CPUID answers never leave the kernel module at all.

- **Hyper-V assist page.** `kvm_hv_get_assist_page` in `hyperv.c`
  reads 56 bytes (`offsetofend current_nested_vmcs`) instead of the
  full 4 KB page. KVM only ever consumes the head fields.

- **Never cache the vmcb12 mapping across transitions.** `hvix64`'s
  early boot churns through vmcb12 contexts. A persistent pin
  triple-faulted L2 in testing.

- **Never skip the nested TLB flushes on shared ASIDs.** Windows will
  not boot as L2 without them.

### Reverted (broke boot)

These were tried and pulled because Windows spun in a fatal `jmp $`
loop (`0xEB 0xFE`) at a kernel address, one vCPU stuck at 99%,
`RBX=0xb RCX=0xf RDX=0xf`:

- Routing `SVM_EXIT_VMMCALL` to a custom `vmmcall_interception`
  instead of stock `kvm_emulate_hypercall`.
- Making `emulator_fix_hypercall` raise `#UD` unconditionally instead
  of following the quirk.
- The `svm_ud_interception` and `vmmcall_interception` functions
  themselves, removed along with the above.

The root cause: forcing VMCALL/VMMCALL to `#UD` broke Windows' own
hypercall use during boot, especially with `<hyperv>` enlightenments
on. VMAware's KVM_INTERCEPTION check does not need this. It only
needs VMCALL to not carry a page-fault tell. Stock hypercall handling
already satisfies that.

---

## 5. Detections already closed (for reference)

- **SVM_EXCEPTIONS**: VMAware runs `VMLOAD` (`0F 01 DA`) at CPL3 and
  expects `#UD`. Closed by the `#GP` intercept + CPL3 `#UD` path
  (§4).
- **Hypervisor string, VMID, CPUID hypervisor bit**: closed by the
  L2 CPUID track+patch (§4).
- **Interrupt shadows, single-step behavior, power capabilities,
  boot logo**: these pass once the L2 CPUID rewrite and the existing
  QEMU/ACPI patches (`fake_battery.aml`, `spoofed_devices.aml`,
  SMBIOS rewrite) are all in place.
- **HYPERV_HOST classification** needs the root-partition bit
  (`0x40000003` EBX bit 0), the `"Microsoft Hv"` vendor string, and
  a measured-boot log. All three come from the same L2 CPUID
  rewrite.

---

## 6. MEASURED_BOOT: fixed, awaiting a guest reboot to confirm

VMAware reads the TBS TCG log for event
`EV_EFI_PLATFORM_FIRMWARE_BLOB` (event `0x80000008`, PCR 0) and
compares it against OVMF's known firmware-volume bounds. The test is
an exact match on the address and length pair
(`vmaware.hpp`, `measured_boot()`):

```c
if ((base_addr == 0x830000 && blob_len == 0xD0000) ||   /* PEIFV */
    (base_addr == 0x900000 && blob_len == 0xE80000)) {  /* DXEFV */
    return true;
}
```

Both branches test the base address, so moving either volume defeats
the match. The lengths are left alone.

Fix: the EDK2 patch (`patches/EDK2/AMD-edk2-stable202605.patch`)
moves `MEMFD_BASE_ADDRESS` from `0x800000` to `0x820000` in
`OvmfPkg/Include/Fdf/OvmfPkgDefines.fdf.inc`. Every volume inside
MEMFD is placed at a fixed offset from that base
(`OvmfPkg/Include/Fdf/MemFd.fdf.inc`: PEIFV at `+0x030000`, DXEFV at
`+0x100000`), so one define moves both.

Built and installed on 2026-08-28, then rebuilt the same day to add
the host firmware metadata described in §9. The compiled-in constants
in `Build/OvmfX64/RELEASE_GCC/X64/OvmfPkg/Sec/SecMain/DEBUG/AutoGen.h`
confirm the new layout:

| PCD | Value now | VMAware expects |
|---|---|---|
| `PcdOvmfPeiMemFvBase` | `0x850000` | `0x830000` — no match |
| `PcdOvmfPeiMemFvSize` | `0x0D0000` | `0x0D0000` |
| `PcdOvmfDxeMemFvBase` | `0x920000` | `0x900000` — no match |
| `PcdOvmfDxeMemFvSize` | `0xE80000` | `0xE80000` |

Only `OVMF_CODE.fd` changed. `OVMF_VARS.fd` is the variable store and
does not depend on `MEMFD_BASE_ADDRESS`; the build produced a
byte-identical template, so the deployed copy (which carries the
host's enrolled Secure Boot keys) and the per-domain NVRAM at
`/var/lib/libvirt/qemu/nvram/aptwannabe_VARS.fd` both stay valid.

The previous firmware is kept at
`/opt/vmw/firmware/OVMF_CODE.fd.pre-memfd.bak`. To roll back:

```bash
echo "$VMW_SUDO" | sudo -S cp /opt/vmw/firmware/OVMF_CODE.fd.pre-memfd.bak \
                         /opt/vmw/firmware/OVMF_CODE.fd
```

### Power-cycled onto the new firmware, 2026-08-28

pflash images load at domain start, so a reboot from inside the guest
keeps the old firmware. The domain has to be stopped and started.

The graceful shutdown did not work. `virsh shutdown` delivered the
ACPI power button event and the guest ignored it for several minutes
while still serving RDP and RPC. This domain has no
`qemu-guest-agent` channel, so libvirt has no stronger lever than the
power button. The VM was forced off with `virsh destroy` and started
again.

The boot was clean: Windows reached RDP in about 25 seconds, with no
BitLocker recovery prompt, so nothing on this guest is sealed to
PCR 0 in a way the firmware change disturbs. Confirmed the running
QEMU has the new image by reading its open file handles:
`/proc/<pid>/fd` shows `/opt/vmw/firmware/OVMF_CODE.fd` as pflash0.

The per-domain NVRAM was copied to
`/var/lib/libvirt/qemu/nvram/aptwannabe_VARS.fd.pre-newfw` before the
first boot on the new firmware.

Note that `-debugcon` writes to `/tmp/ovmf-debug.log`, but the
firmware is built `-b RELEASE`, so that file stays empty. Runtime
verification of the FV addresses would need a `DEBUG` build.

**Still to do:** run VMAware inside the guest and confirm
MEASURED_BOOT now reports clean. Until then the 2/85 figure in §3 is
the old measurement.

If a future firmware change does trip a BitLocker recovery prompt,
suspend protection for one boot from inside the guest first:

```powershell
manage-bde -status C:
manage-bde -protectors -disable C: -RebootCount 1
```

---

## 6b. BOOT_LOGO: the stock EDK2 logo was shipping (fixed 2026-08-28)

A VMAware run on 2026-08-28 reported BOOT_LOGO detected, with
`crc=0x110350c5`. That value is not incidental. VMAware hashes the
boot logo and compares against two known constants:

```c
switch (hash) {
    case 0x110350C5: return core::add(brand_enum::QEMU);   /* TianoCore EDK2 */
    case 0x87c39681: return core::add(brand_enum::HYPERV);
    default:         return false;
}
```

The guest was publishing the stock TianoCore logo. Cause: phase 3 of
`patch_ovmf()` replaces `MdeModulePkg/Logo/Logo.bmp` with the host's
BGRT image, and like phase 2 (§9) it had never run on this tree.
`git status` confirmed `Logo.bmp` was pristine.

Fix: copy `/sys/firmware/acpi/bgrt/image` over
`MdeModulePkg/Logo/Logo.bmp` and rebuild. The host BGRT passes EDK2's
decoder rules (see `REFERENCE.md`): 505x98, 24 bpp, uncompressed.

### The hash is not taken over the file

Worth recording, because it misleads. The stock `Logo.bmp` is 12,446
bytes and hashes (crc32c) to `0x63CD1A69`, which is **not**
`0x110350C5`. The guest reported a 33,694-byte bitmap. So Windows is
not returning the file: `NtQuerySystemInformation`
(`SystemBootLogoInformation`, class 140) returns the BGRT bitmap that
OVMF **re-encodes** from `Logo.bmp` at boot, at different dimensions
and colour depth.

The practical consequence is that the resulting hash cannot be
predicted from the source file. Changing the logo is guaranteed to
change what gets published, and so to miss both hardcoded constants,
but the only way to learn the new value is to boot and re-run
VMAware.

---

## 6c. Open: POWER_CAPABILITIES

Reported detected on the same run, with
`!(S0||S1||S2||S3||S4||H) pattern` — the guest advertises no sleep
states at all. VMAware's logic (`power_capabilities()`, reading
`NtPowerInformation` / `SystemPowerCapabilities`):

| Pattern | Verdict |
|---|---|
| `(S0 \|\| S3) && (S4 \|\| HiberFilePresent)` | physical, passes |
| `!(S0\|\|S3\|\|S4\|\|Hiber) && (S1\|\|S2)` | VM |
| nothing supported at all | VM — **this is us** |

To pass, the guest needs one of S0 or S3, **and** one of S4 or a
hibernation file. Note this is not a spoofable string; it is what
Windows believes about its own power hardware.

The libvirt side is already correct. The live domain carries:

```xml
<pm>
  <suspend-to-mem enabled='yes'/>
  <suspend-to-disk enabled='yes'/>
</pm>
```

and `genxml.py` emits that from the profile's `pm:` block. So QEMU
advertises S3 and S4 in ACPI, and something inside Windows is
discarding them.

The likely cause is Hyper-V. A Windows instance running as a Hyper-V
root partition hands power management to the hypervisor, which
historically drops S3 and S4. That fits this project exactly: §1
notes the same tension, and this is another instance of it —
turning Hyper-V on costs a detection surface.

Nothing has been changed yet. The next step is a diagnostic, not a
fix. Run this in the guest:

```powershell
powercfg /a
```

It lists every standby state and, for the unavailable ones, the
reason — distinguishing "the firmware does not support this state"
(an ACPI problem we can fix in QEMU) from "the hypervisor does not
support this state" (a Hyper-V consequence, much harder).

### What `powercfg /a` reported

Run in the guest on 2026-08-28:

| State | Blocked by |
|---|---|
| S1, S2 | firmware **and** hypervisor |
| S3 | **hypervisor only** |
| Hibernate | **hypervisor only** |
| S0 Low Power Idle | **firmware only** |
| Hybrid Sleep, Fast Startup | derived from the above |

Read the reasons, not just the list. S3 and hibernate are gone
because hvix64 refuses them, and that is not negotiable while goal 2
stands. S0 low-power idle was refused by *our* firmware, which we do
control. That made it the only candidate.

### Hibernation is not needed

Worth stating, because it looks like a blocker and is not. The
physical pattern `(S0 || S3) && (S4 || Hiber)` is unreachable here.
But failing it does not mean detected — the function falls through to
two VM patterns, and `S0 = true` defeats both, because each begins
`!(S0 || S3 || S4 || Hiber)`. Execution then reaches the
manufacturer check at the end, which returns "not a VM" outright for
Lenovo, Qiyida, or a Dell Latitude. Our `smbios.bin` reports
`LENOVO` / `Legion 5 15ACH6`, and VMAware reads the manufacturer from
`HKLM\HARDWARE\DESCRIPTION\System\BIOS\SystemManufacturer`.

So **S0 alone is sufficient**. `powercfg /h on` is not needed.

Note also that enabling S1 or S2 would make things *worse*: the first
VM pattern is `!(S0||S3||S4||Hiber) && (S1||S2)`, so S1/S2 without S0
is an explicit VM signature.

### Attempted and reverted: FADT Low Power S0 Idle Capable

Two changes were made to `hw/i386/acpi-build.c` and both are now
reverted. Recorded here so the next person does not repeat them.

**Step 1 — set the flag.** Added
`(1 << ACPI_FADT_F_LOW_POWER_S0_IDLE_CAPABLE)` (FADT flags bit 21) to
`init_common_fadt_data()`. The guest booted fine, but `powercfg /a`
was unchanged. Dumping the guest FADT through
`GetSystemFirmwareTable` showed why:

```
FADT revision = 3
FADT flags    = 0x002084A5
bit21 LowPowerS0IdleCapable = 1
```

The flag reached the guest. Windows ignored it, because
`LOW_POWER_S0_IDLE_CAPABLE` is an ACPI 5.0 addition and QEMU builds
the x86 FADT at revision 3. Windows validates the revision before
honouring flags from later specs.

**Step 2 — bump the revision.** Changed `.rev = 3` to `.rev = 5`,
leaving `SLEEP_CONTROL_REG` and `SLEEP_STATUS_REG` zeroed, which
ACPI 5.0 permits when `HW_REDUCED_ACPI` is clear (q35 keeps the
legacy PM1 registers). The `rev = 1` override further down is
piix-only, for Windows 2000, so q35 was the only machine affected.

**This broke the guest.** Windows never reached RDP. One vCPU pinned
at 100% and `info registers` showed RIP frozen at
`fffff80521764e52` across samples — an ntoskrnl address, the same
fatal spin signature as the kernel-patch boot hangs in §4. Reverted;
the rebuilt binary is byte-identical to the pre-change backup
(md5 `79c13a8c…`), and the guest boots normally again.

Whether rev 5 needs the sleep registers actually populated rather
than zeroed was not tested. Each attempt costs a hung guest and a
manual recovery cycle, so it was not worth continuing blind.

### Fixed by registry override, 2026-08-28

The firmware route was abandoned. What works instead is a single
registry value, applied in the guest:

```
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Power" ^
  /v PlatformAoAcOverride /t REG_DWORD /d 1 /f
```

Reboot, and Windows reports `AoAc`. That sets S0, which is all the
check needs (see "Hibernation is not needed" above). Confirmed
working. To undo:

```
reg delete "HKLM\SYSTEM\CurrentControlSet\Control\Power" ^
  /v PlatformAoAcOverride /f
```

VMAware's own source comments on this key without acting on it:

```c
/* Could check for HKLM\SYSTEM\CurrentControlSet\Control\Power\PlatformAoAcOverride */
```

So this fix is one upstream commit away from being detected. It is a
registry artifact, not a hardware property, and it is weaker than a
firmware fix would have been. Treat it as provisional, and note it
does nothing for the ring-0 goals in `README.md`, where a detector is
free to read the same key.

The firmware route is not closed, just unproven. The narrow open
question: does an x86 FADT at revision 5 boot Windows 10 19045 when
`SLEEP_CONTROL_REG` and `SLEEP_STATUS_REG` hold real registers rather
than zeros? Note that the host's own FADT is revision 5, length 268,
with **both of those registers zeroed** — so the shape used above
matches shipping Lenovo firmware, which is why the hang is more
likely to have come from Windows initialising Modern Standby without
a Power Engine Plugin than from the table itself. Untested, because
the registry override made it unnecessary.

---

## 7. Open: TIMER memory-ratio

### What VMAware measures

VMAware creates its own L2 partition through the public WHP API
(`WHvCreatePartition`, `WHvSetupPartition`,
`WHvCreateVirtualProcessor`, `WHvMapGpaRange`), maps 0x2000 bytes,
drops the vCPU into real mode, then deliberately reads an unmapped
GPA (`0x3000`). That forces a nested page fault (NPF) that only
`hvix64` can resolve, because the fault exists in `hvix64`'s own
second-level table for this L2, not in ours. It compares the time
that round trip takes against 2256 calls to `NtQuerySystemTime`, a
syscall loop that never triggers a VM exit at all. The ratio has to
stay under 4.0 (`vmaware.hpp`, function `timer()`, around line
7040).

### Why the existing path cannot be sped up under threshold

We traced the call path in this session
(`arch/x86/kvm/svm/nested.c`, `nested_svm_init_mmu_context()` and
`nested_svm_inject_npf_exit()`):

1. Two real hardware VM transitions happen: L2 exits to the host,
   and the host re-enters the guest so `hvix64` can see the fault.
2. Before that, the host has to walk `hvix64`'s own in-memory
   second-level page table for this L2, cold. The probe is one-shot,
   so there is no cache to warm the way the CPUID fastpath (§4)
   does. CPUID never touches memory at all; this fault necessarily
   does.
3. `hvix64` itself then does real, un-inspectable work to turn the
   fault into a `MemoryAccess` exit and hand it back to the calling
   process through the NT kernel.

None of that work is ours to skip. It matches what upstream KVM
developers have already found: the dual-ASID nested-virtualization
series (Yosry Ahmed, ~28 patches, posted to lkml in 2026) reports
8 to 17 percent gains in its own benchmarks. That would put this
ratio at roughly 4.9 to 5.4 in the best case, still over the 4.0
threshold. Our own experiments point the same way: removing the
exit-side TLB flush moved the ratio from 5.97 to 5.87, inside
measurement noise. Two things we tried and reverted because they
broke L2 boot outright: caching the vmcb12 mapping across
transitions, and skipping the nested TLB flush on shared ASIDs
(also listed as permanent rules in §4).

**Conclusion: this is not a tuning problem.** The gap between our
current 5.94 and the 4.0 threshold cannot close by making the
forward path faster. It closes only by keeping VMAware's probe from
producing a valid measurement in the first place.

### The one real option

`vmaware.hpp` shows that if any WHP setup call fails,
`check_nested_hypervisors` is set to `false`, and the whole
memory-ratio block is skipped. It is not defaulted to a safe value;
it is never evaluated at all (confirmed by reading the source
directly, `vmaware.hpp` lines 6670 to 6680 and 7039).

The catch: the host never sees a `WHvCreatePartition` call as such.
It is serviced entirely inside the guest, by `hvix64`. The earliest
point the host can act is the **first VMRUN into a brand-new vmcb12
context** that `hvix64` creates for that partition. VMAware's own
probe has a fairly specific shape at that moment: `CR0 =
0x60000010` (real mode, paging off), `EFER = 0`, one vCPU, about
8 KB mapped, appearing well after the guest has already finished
booting into long mode.

That shape should not match:

- Your own legitimate WHP use for VBS/HVCI research (goal 2). A
  real workload maps real memory, not 8 KB.
- VBS/VTL1 itself, which does not create a second partition at all.
  A Virtual Trust Level is a protection-domain switch inside the
  *same* partition, so it should never hit this code path. But this
  assumption is not yet checked against the Hyper-V TLFS.

This is genuinely untried, and it is the same category of change
that caused every boot-hang revert in §4. **Before writing any code
that can fail a VMRUN, instrument first.** Log the initial
CR0/EFER/vCPU-count of every fresh vmcb12 context after boot,
across a normal session and a real WHP test program (not VMAware).
Confirm the probe's shape is unique before trusting it enough
to act on.

---

## 8. VM configuration notes (`configs/aptwannabe.yml`)

- CPU: `host-passthrough`, `check='none'`, `migratable='off'`,
  topology 1 socket / 4 cores / 2 threads. Both 4c/2t and 8c/1t boot.
  4c/2t is the current setting, kept from an earlier hang bisection.
- `nrip` is unknown to libvirt 12.5 and must stay out of the SVM
  feature list. Verify the SVM feature set stays correct now that
  Hyper-V is on. It was tuned for Hyper-V originally.
- `<hyperv mode='custom'>` currently sets: relaxed, vapic,
  spinlocks (4095), vpindex, runtime, synic, stimer, reset,
  frequencies, reenlightenment. Research suggested also adding
  `time`, `stimer-direct`, `tlbflush`, `emsr-bitmap`,
  `tlbflush-direct`, and `xmm-input`. Libvirt 12.5 only recognizes
  `time` and `tlbflush` in its schema, and the QEMU driver rejected
  both. The nested-specific ones need a newer libvirt or raw QEMU
  args.
- `<kvm><hidden state='on'/></kvm>`: the hypervisor bit is hidden
  from the guest's own CPUID view.
- `hypervclock` timer is present.
- Networking: DHCP hands out `192.168.122.85` (hostname
  `DESKTOP-FNKT0LT`, MAC 52:54:00:e1:1a:96). RDP (3389) and msrpc
  (135) are open. ICMP is blocked by the guest firewall. Lease
  file: `/var/lib/libvirt/dnsmasq/virbr0.status`.

---

## 9. Known gap: the tool does not rebuild the working VM

The running `aptwannabe` domain depends on four files in
`/opt/vmw/firmware/`. Only one of them is produced by a module:

| File | Produced by | Status |
|---|---|---|
| `smbios.bin` | `modules/qemu.sh`, `spoof_smbios()` | Automated |
| `OVMF_CODE.fd`, `OVMF_VARS.fd` | `modules/edk2.sh`, `build_ovmf()` | Automated |
| `fake_battery.aml` | nothing | Copied by hand from `patches/QEMU/` |
| `spoofed_devices.aml` | nothing | Copied by hand from `patches/QEMU/` |
| `vbios.rom` | nothing | Dumped by hand (see `resources/scripts/Linux/vbios-dumper.sh`) |

The domain XML has the same problem. `python/vmw/genxml.py` emits the
`-smbios` argument and nothing else under `qemu:commandline`. The
live domain also carries:

- Two `-acpitable` arguments, for `fake_battery.aml` and
  `spoofed_devices.aml`.
- A full machine argument string
  (`pc-q35-11.0,usb=off,vmport=off,smm=on,i8042=off,...`).
- The GPU passthrough `hostdev` entries.

None of those come from the generator. They were added to the domain
by hand after `vmw deploy` ran.

**What this means in practice:** running `vmw setup aptwannabe` on a
fresh machine today produces a VM that boots but is *not* the VM
this research was done on. It would be missing the fake battery,
the custom device tables, and the machine arguments. Several of
those close detections listed in §5. Reproducing the current result
needs the manual steps above.

Closing this gap means teaching `genxml.py` to emit `-acpitable`
arguments and arbitrary machine arguments from the profile. It also
needs an install step that copies the `.aml` files into
`/opt/vmw/firmware/`. That work is not started.

### The firmware metadata rewrite had never run (fixed 2026-08-28)

Found while rebuilding OVMF for §6. `patch_ovmf()` in
`modules/edk2.sh` has a second phase that rewrites firmware identity
strings with `sed`, using values read from this host. On the tree at
`src/edk2-stable202605`, that phase had never run, so the firmware
shipped `EDK II` as its UEFI vendor string — readable from the guest
through the EFI system table. VMAware does not test it, which is why
every other check still passed, but a ring-0 detector may.

The static patch adds "modified via edk2.sh" marker comments to
exactly the lines phase 2 targets. That makes the files show as
modified in `git status` while their values are untouched, which is
what hid the problem.

Phase 2 was applied to the tree and the firmware rebuilt. The values
now compiled in:

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

These now agree with the OEM ID and table ID that `modules/qemu.sh`
writes into QEMU's `aml-build.c`, so the firmware and the emulator
report the same identity instead of disagreeing.

**A bug in `edk2.sh` was fixed at the same time.** The
`PcdAcpiDefaultOemId` substitution matched `"INTEL "` *including its
quotes* but put back a bare word:

```sed
s@(PcdAcpiDefaultOemId)\|"INTEL "\|@\1|'"$OEMID"'|@     # before
s@(PcdAcpiDefaultOemId)\|"INTEL "\|@\1|"'"$OEMID"'"|@   # after
```

The result would have been `PcdAcpiDefaultOemId|LENOVO|VOID*|...`,
which is not valid for a `VOID*` PCD. Every other string substitution
in that block re-adds its quotes; this one was the exception. Phase 2
also now refuses to run when the FADT read returns nothing or the OEM
ID is not exactly 6 bytes, instead of writing an empty value into the
firmware.

Note that phase 2 must be applied to the existing tree. A clean
re-clone would drop the MEMFD fix from §6 along with everything else,
until `vmw patch-check edk2` and a fresh `git apply` put it back.

Phase 3, the boot logo replacement, had never run either. See §6b.
Both phases live in `patch_ovmf()`, which only executes on the
clone path in `acquire_edk2_source()`. Answering "no" to the purge
prompt on an existing tree skips straight to the build, so a tree set
up that way never receives phases 2 and 3 at all. That is the
underlying reason two separate detection surfaces were left open.

---

## 10. Useful commands

```bash
# sudo (password read into $VMW_SUDO once per shell, never stored)
read -rs VMW_SUDO
echo "$VMW_SUDO" | sudo -S <command>

# Start the VM / reload kvm_amd if it didn't autoload
echo "$VMW_SUDO" | sudo -S virsh --connect qemu:///system start aptwannabe
echo "$VMW_SUDO" | sudo -S modprobe kvm_amd

# Rebuild the kernel (fast: ccache is set up, ~5-10 min instead of ~60)
cd src/linux-tkg
git -C linux-src-git reset --hard && git -C linux-src-git clean -ffdx
rm -f *.pkg.tar.zst
setsid nohup makepkg -sf --noconfirm > /tmp/kernel-build.log 2>&1 < /dev/null &
# then: pacman -U both built packages (dkms hooks take ~5 min), then reboot

# Verify the kernel patch still applies to a clean v7.0 tree
vmw patch-check kernel

# Regenerate patches/checksums.sha256 after editing a patch
PYTHONPATH="$PWD/python" python3 -m vmw.patches gen

# Watch the guest for the jmp-$ boot hang (frozen RIP + one vCPU at 99%)
echo "$VMW_SUDO" | sudo -S virsh --connect qemu:///system qemu-monitor-command \
  aptwannabe '{"execute":"human-monitor-command","arguments":{"command-line":"info registers"}}'
# read guest code at the frozen RIP: gva2gpa <RIP>, then xp/Nbx <gpa>
```

Rebuild OVMF without the interactive module. The source tree at
`src/edk2-stable202605` already has the patch applied, so this skips
straight to the build. It takes about 20 seconds incrementally, or a
few minutes from clean:

```bash
cd src/edk2-stable202605
export WORKSPACE="$(pwd)"
export EDK_TOOLS_PATH="$WORKSPACE/BaseTools"
export CONF_PATH="$WORKSPACE/Conf"
[[ -x BaseTools/Source/C/bin/GenFv ]] || make -C BaseTools -j"$(nproc)"
source edksetup.sh
build -p OvmfPkg/OvmfPkgX64.dsc -a X64 -t GCC -b RELEASE -n 0 -s \
  -D SECURE_BOOT_ENABLE=TRUE -D SMM_REQUIRE=TRUE \
  -D TPM1_ENABLE=TRUE -D TPM2_ENABLE=TRUE

# check the FV bases landed where you expect, then install
grep _PCD_VALUE_PcdOvmfPeiMemFvBase \
  Build/OvmfX64/RELEASE_GCC/X64/OvmfPkg/Sec/SecMain/DEBUG/AutoGen.h
echo "$VMW_SUDO" | sudo -S cp -a /opt/vmw/firmware/OVMF_CODE.fd \
                            /opt/vmw/firmware/OVMF_CODE.fd.bak
echo "$VMW_SUDO" | sudo -S cp Build/OvmfX64/RELEASE_GCC/FV/OVMF_CODE.fd \
                         /opt/vmw/firmware/OVMF_CODE.fd
```

Running `modules/edk2.sh` instead re-runs the whole flow, including
the prompt to purge and re-clone the source tree. Answer "no" to the
purge prompt to keep the patched tree.

Note that pflash images load at domain start. A reboot from inside
the guest keeps the old firmware; the guest must be shut down and
started again.

Other reference points:

- Build-tree copy of the kernel patch, kept in sync with
  `patches/Kernel/amd702.mypatch`:
  `src/linux-tkg/linux70-tkg-userpatches/amd702.mypatch`
- Kernel source worktree: `src/linux-tkg/linux-src-git`
- Custom QEMU binary: `/opt/vmw/emulator/bin/qemu-system-x86_64`
- Firmware: `/opt/vmw/firmware/` (`OVMF_CODE.fd`, `OVMF_VARS.fd`,
  `smbios.bin`, `fake_battery.aml`, `spoofed_devices.aml`,
  `vbios.rom`)
- Full VM XML: `virsh --connect qemu:///system dumpxml aptwannabe`
- NotebookLM notebook "Virtualization Research"
  (id `738890c6-8fec-456f-a019-adc674a4c242`) holds the AMD manual,
  the Hyper-V TLFS, and papers used to check claims against
  citations.

---

## Appendix: a note on repo layout

This document lives at the repo root next to `README.md` because
that is where `passoff.md` used to live and where you will look for
it first. If this grows past what one file should hold, for instance
once §7's instrumentation work produces real log data, the natural
split is:

- `docs/research/` for narrative findings like this file (one file
  per detection category, or per open question).
- `docs/research/logs/` for raw instrumentation output, kept out of
  `logs/` (which is the tool's own run logs, already gitignored).

No files move as part of writing this document. That split is a
proposal for a later pass, not something done here.
