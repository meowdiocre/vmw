# Usage

## CLI

Every TUI action has a matching headless subcommand, so the tool
works over SSH.

```
vmw                          Launch the dashboard TUI
vmw status                   Probe each step and show domain state
vmw plan <profile>           List the actions a setup would run (dry-run)
vmw setup <profile>          Run all six steps in order
vmw rebuild <step> <profile> Force one step (dev loop)
vmw deploy <profile>         Generate and define the libvirt domain
vmw profile list|validate|new  Manage YAML profiles
vmw patch-status             Verify patch checksums and target versions
vmw patch-add <path> [ver]   Stamp a patch header and refresh checksums
```

## Profiles

Each VM is one YAML file in `configs/`, validated by the pydantic
schema in `python/vmw/profiles/schema.py`. Create or edit a profile
in the TUI (`n` / `e` on the dashboard), or from the CLI:

```console
$ vmw profile new <name>
```

The editor writes YAML while preserving existing comments.
`python/vmw/genxml/` turns a profile into a libvirt domain XML,
validated against the libvirt schema before `virsh define`.

### Shared defaults

`configs/_defaults.yml` holds the values common to every VM. Each
profile is loaded on top of it (deep-merged, profile wins), so a
profile file carries only what differs — typically just `name`,
`vm.memory_mib`, and the disk. `_defaults.yml` is a base, not a
selectable profile: it never appears in `vmw profile list`.

### One profile, any machine

A profile pins no CPU-specific patch. Leaving `patches.{kernel,qemu,edk2}`
empty (the default) tells the build to derive the Intel or AMD patch
from the host CPU at build time, so the same profile builds on an Intel
or an AMD host unchanged. Set a value only to force a specific file in
`patches/{Kernel,QEMU,EDK2}/`.

## Build steps

A setup runs six steps in order: virtualization, kernel, QEMU, EDK2,
VFIO, deploy. Each step is probed, planned, and resumable. `vmw plan
<profile>` prints what a run would do without executing anything.
`vmw rebuild <step> <profile>` forces one step to run again.

## Patches

Every patch under `patches/` is SHA256-verified against
`patches/checksums.sha256`. Each patch is stamped with its target
source version.

Add or update a patch:

```console
$ vmw patch-add patches/QEMU/AMD-v11.0.4.patch v11.0.4
$ vmw patch-status
```

## Prerequisites

- `git`, `python3` (3.11+); `pip install -e .` pulls the rest
- A supported Linux distribution
- UEFI/BIOS settings: CPU virtualization extensions (VT-x / AMD-V),
  IOMMU support (VT-d / AMD-Vi)
- A dGPU for passthrough (recommended)
