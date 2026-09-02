# TIMER (memory-ratio)

The instruction-ratio component of VMAware's TIMER check is closed by
the [L2 CPUID fastpath](index.md#what-it-patches). The memory-ratio
component is open.

## What VMAware measures

VMAware creates its own L2 partition through the public WHP API
(`WHvCreatePartition`, `WHvSetupPartition`,
`WHvCreateVirtualProcessor`, `WHvMapGpaRange`), maps 0x2000 bytes,
drops the vCPU into real mode, then reads an unmapped GPA (`0x3000`).
The read forces a nested page fault that only `hvix64` can resolve,
since the fault exists in `hvix64`'s own second-level table for this
L2. VMAware compares that round trip against 2256 calls to
`NtQuerySystemTime`, a syscall loop that never triggers a VM exit.
The ratio must stay under 4.0 (`vmaware.hpp`, `timer()`, around line
7040).

## Why the current path cannot close the gap

Closing the ratio through speed requires cutting either of two
hardware VM transitions (L2 exit to host, host re-entry so `hvix64`
sees the fault) or the cold walk of `hvix64`'s in-memory second-level
page table for this L2 — the probe is one-shot, so the CPUID
fastpath's per-vCPU cache does not apply; the fault necessarily
touches memory that CPUID never does. None of that path belongs to
this patch; it runs inside `hvix64` itself.

Upstream KVM's dual-ASID nested-virtualization series (Yosry Ahmed,
~28 patches, posted to lkml in 2026) reports 8–17 percent gains in
its own benchmarks, which would put this ratio at roughly 4.9–5.4 in
the best case — still over the 4.0 threshold. The measured ratio on
this build is 5.94.

**This is not a tuning problem.** The gap between the current ratio
and the 4.0 threshold does not close by making the forward path
faster. It closes only by keeping VMAware's probe from producing a
valid measurement in the first place.

## The remaining option

`vmaware.hpp` sets `check_nested_hypervisors = false` if any WHP
setup call fails, and skips the entire memory-ratio block —
unevaluated, not defaulted to a safe value (confirmed by reading
`vmaware.hpp` lines 6670–6680 and 7039 directly).

The host never sees a `WHvCreatePartition` call as such; it is
serviced entirely inside the guest, by `hvix64`. The earliest point
the host can act is the first VMRUN into a brand-new vmcb12 context
that `hvix64` creates for that partition. VMAware's own probe has a
specific shape at that moment: `CR0 = 0x60000010` (real mode, paging
off), `EFER = 0`, one vCPU, about 8 KB mapped, appearing after the
guest has already finished booting into long mode. That shape should
not match legitimate WHP use for VBS/HVCI, which maps real memory,
not 8 KB, or VBS/VTL1 itself, which is a protection-domain switch
inside the same partition and does not create a second partition —
though this assumption is not yet checked against the Hyper-V TLFS.

Failing a VMRUN on the wrong context is the same class of change that
has caused nested-boot regressions in this patch before (see
[Kernel: constraints that must hold](index.md#constraints-that-must-hold)).
Any implementation of this option needs the initial
CR0/EFER/vCPU-count of every fresh vmcb12 context logged first,
across a normal session and a real WHP test program, to confirm the
probe's shape is unique before code acts on it.
