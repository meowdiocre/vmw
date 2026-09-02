# Kernel

`patches/Kernel/amd702.mypatch` changes eight files:
`arch/x86/kvm/{cpuid.c, emulate.c, x86.c, hyperv.c, svm/svm.c,
svm/nested.c, svm/svm.h}`, and `include/linux/percpu.h`.
`steps/kernel.py` clones `linux-tkg`, stages the patch, and builds.

See [TIMER](timer.md) for the one open detection this layer cannot
yet close.

## Regenerating the patch

The patch is built by copying every changed file into a pristine
clone of the target kernel tree and running `git diff`. Copy all
eight files every regeneration, even the ones untouched
this round — copying only the edited files drops old hunks silently
and reintroduces detections that were already fixed.

## What it patches

**percpu allocation.** `PERCPU_MODULE_RESERVE` goes from 8 KB to
32 KB in `include/linux/percpu.h`. `kvm_amd` needs 7280 bytes of
percpu space; without this it fails to load ("Could not allocate
7280 bytes percpu data"), `/dev/kvm` never appears, and libvirt
refuses to define the domain.

**CPUID cache.** `handle_cpuid` gets a per-CPU cache
(`VMW_CPUID_CACHE_ENTRIES=256`) so repeated `(leaf, subleaf)` lookups
skip `kvm_emulate_cpuid`.

**VMCALL/VMMCALL raise a clean `#UD`.** `EmulateOnUD` is removed
from the VMCALL and VMMCALL opcode entries in `emulate.c`, so these
instructions fault instead of being emulated after interception.
This closes VMAware's `KVM_INTERCEPTION` check, which flags an
access violation when it observes KVM patching instructions live.
The patch keeps stock hypercall handling underneath — forcing
VMCALL/VMMCALL to `#UD` unconditionally breaks Windows' own
hypercall use during boot, and the check only needs VMCALL to not
carry a page-fault tell, which stock handling already satisfies.

**P-state / CPPC MSR passthrough.** MSRs `0xc0010062`–`0xc001006b`,
`0xc0010293`, `0xc001029a`, and `0xc00102b0`–`0xc00102b3` read
through `rdmsr_safe` in `kvm_get_msr_common` and accept writes
silently in `kvm_set_msr_common`. `svm.c` disables read interception
for the same ranges. This is the CPU-Z "max multiplier" fix.

**CPUID leaf 7 mask.** `entry->edx &= 0x73FFFFFF;` masks
AMD-reserved hypervisor bits after the leaf-7 EDX override.

**MCE gate removal.** `x86.c` drops the `MCG_CTL_P` and `MCG_CMCI_P`
checks in `set_msr_mce` and `get_msr_mce`, and comments out the XSS
read/write gates (for XSAVES).

**Hypercall quirk.** `svm_vm_init` sets `disabled_quirks |=
KVM_X86_QUIRK_FIX_HYPERCALL_INSN`.

**Native intercepts cleared.** RDTSC/RDTSCP, RDPMC, INVD, INVLPGA,
TASK_SWITCH, WBINVD, RDPRU, VMLOAD/VMSAVE/STGI/CLGI/SKINIT.

**`#GP` intercept and CPL3 `#UD`.** `init_vmcb` turns on
`GP_VECTOR` interception unconditionally. `gp_interception` turns a
CPL3 SVM-instruction fault into `#UD`, matching bare metal's `#UD`
response to `VMLOAD` at CPL3. This closes VMAware's
`SVM_EXCEPTIONS` check.

**L2 CPUID track and patch.** `svm_vmw_track_l2_cpuid()`, called
from the nested branch of `svm_handle_exit`, records the L2 CPUID
leaf and exit RIP, then forwards the exit to `hvix64` untouched.
`svm_vmw_patch_l2_cpuid_answer(vcpu, vmcb12)`, called from
`nested_svm_vmrun()`, waits for L2 to resume at `exit_rip + 2` and
patches only the detection-relevant bits of the answer:

- Leaf `0x40000000`: RBX/RCX/RDX become `"Micr"`/`"osof"`/`"t Hv"`.
- Leaf `0x40000003`: RBX gets the root-partition bit (`| 1`).
- Leaf `0x40000006`: RAX clears bits `0x3c00`.

SVM's VMRUN only loads RAX/RSP/RIP from the VMCB, so RBX/RCX/RDX
reach L2 through `vcpu->arch.regs`; the patch writes both `vmcb12`
and `regs`. This closes the hypervisor-string, VMID, CPUID
hypervisor-bit, and `HYPERV_HOST` classification checks.

The Windows secure kernel needs the real 128-bit privilege mask from
`hvix64`'s own leaf `0x40000003`. L2 CPUID is never answered with
fabricated values for this reason: a faked privilege mask breaks
VBS/HVCI init at boot, with CPU0 halted in the kernel and every vCPU
idle.

**L2 CPUID fastpath.** `svm_vmw_answer_l2_cpuid_fastpath()`, called
from `svm_exit_handlers_fastpath`, answers repeated L2 CPUID from a
per-vCPU cache of `hvix64`'s own previous answers (leaf 0 and the
Hyper-V leaf range only), returning `EXIT_FASTPATH_REENTER_GUEST` —
an IRQs-off re-entry that skips the full exit path. The cache holds
32 entries, keyed on leaf+subleaf, filled by
`svm_vmw_patch_l2_cpuid_answer`; the slow path in `svm_handle_exit`
stays as a fallback. This closes VMAware's TIMER instruction-ratio
component, moving it from 155 to about 11.4 against a 15.0
threshold, since cached CPUID answers never leave the kernel module.

**Hyper-V assist page.** `kvm_hv_get_assist_page` in `hyperv.c`
reads 56 bytes (`offsetofend current_nested_vmcs`) instead of the
full 4 KB page; KVM only consumes the head fields.

## Constraints that must hold

- The vmcb12 mapping is never cached across transitions. `hvix64`'s
  early boot churns through vmcb12 contexts; a persistent pin
  triple-faults L2.
- Nested TLB flushes on shared ASIDs are never skipped. Windows does
  not boot as L2 without them.
