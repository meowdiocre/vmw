<div align="center">

# VMW - VM Workspace

A State-Of-Art Linux virtualization research workspace 

It builds and manages a KVM guest that runs Windows with Hyper-V, HVCI,
nested virtualization, and GPU passthrough.

Layers: patched QEMU, EDK2/OVMF firmware, a patched host kernel, VFIO
passthrough, and SMBIOS adjustments.

</div>

---

## Description

**VMW** turns one YAML profile into a full virtualization stack: a
custom kernel, a custom QEMU, custom OVMF firmware, and a libvirt
domain definition. Each layer has a patch set under `patches/`. The
patches change the values that guest software can read: CPUID leaves,
MSR behavior, firmware tables, SMBIOS strings, and TPM identity.

The research target is
[VMAware](https://github.com/kernelwernel/VMAware), an open-source
VM-detection library. The project asks one question: which detection
surfaces can close, and which are inherent to nested virtualization? Also Since VMAware purely live in ring-3 the other goals in here to pass the ring-0 detection as well e.g vanguard faceit and other ring-0 checks.

The guest must stay a working research platform. Hyper-V, HVCI
(Memory Integrity), and nested WHP partitions must keep working. The
RTX 3050 Ti must stay passed through with no Code 43. These goals pull
against each other. Hiding the hypervisor disables nested
virtualization. Keeping it on exposes surfaces that VMAware reads. The
current configuration keeps Hyper-V on and closes what that exposes.

Keep in note tpm attestation research will also covering this repo but in the future.

## Quick start

```sh
git clone --single-branch --depth=1 https://github.com/meowdiocre/vmw
cd vmw/

vmw plan vmud      # review what will happen, nothing executes
vmw                # guided step-by-step setup
```

## CLI

```
vmw [profile]                Guided step-by-step setup (default vmud)
vmw menu                     Interactive menu (pick any module)
vmw plan <profile>           Print the plan, execute nothing
vmw setup <profile>          Run the full automated setup
vmw deploy <profile>         Generate and define the domain XML
vmw patch-status             Verify patch checksums and target versions
vmw patch-check [comp]       Clone sources, verify patches apply cleanly
vmw status                   List profiles, libvirt domains, state
vmw help                     Show this help
```

## Configuration

Each VM is one YAML file in `configs/`. The file `configs/vmud.yml`
is the default profile. Values in the profile replace the interactive
prompts. Omit a value to fall back to the prompt.

`python/vmw/genxml.py` turns the profile into a libvirt domain XML.
The XML is validated against the libvirt schema before `virsh define`.

## Project layout

```
vmw/
├── bin/vmw            CLI entrypoint (guided setup + subcommands)
├── lib/               bash libraries (config, state, run, packages, ...)
│                      loaded via lib/init.sh
├── modules/           per-feature scripts (virtualization, qemu, edk2,
│                      vfio, kernel, deploy)
├── python/vmw/        Python tooling (yaml, state, patches, genxml, patchcheck)
├── configs/           per-VM YAML profiles
├── patches/           versioned patches + checksums.sha256
├── resources/         helper scripts (SMBIOS, vbios dumpers, ...)
├── scripts/           dev workflows (add_patch.sh)
├── .vmw/              local state and caches (gitignored)
├── logs/              runtime logs (gitignored)
└── src/               build artifacts (gitignored)
```

## Patches

Every patch under `patches/` is SHA256-verified against
`patches/checksums.sha256`. Each patch is stamped with its target
source version. To add or update a patch:

```sh
scripts/add_patch.sh patches/QEMU/AMD-v11.0.4.patch v11.0.4
vmw patch-status
```

### Verify patches apply cleanly

`vmw patch-check` clones each source repo at the stamped version. The
version is a QEMU tag, an EDK2 tag with submodules, or an upstream
Linux tag. It runs `git apply --check` on every active patch. It does
not apply anything. Run it before a long build to catch broken or
stale patches.

```sh
vmw patch-check          # all components
vmw patch-check qemu     # one component
vmw patch-check --purge  # delete cached clones and start fresh
```

Cached source trees live in `.vmw/patchcheck/` (gitignored).

## Prerequisites

- `git`, `python3` + `pyyaml` + `lxml`
- Supported Linux distribution
- UEFI/BIOS settings:
  - CPU virtualization extensions (VT-x / AMD-V)
  - IOMMU support (VT-d / AMD-Vi)
- A dGPU for passthrough (recommended)

## Documentation

This file covers how to run the tool. Two companion files cover the
rest:

- `RESEARCH.md`: findings behind the patches in `patches/`. What each
  fix does, why, what broke boot and got reverted, what is still open.
- `REFERENCE.md`: upstream sources and specs for each detection
  surface. It covers QEMU, OVMF firmware, the TPM stack, and the
  kernel.

## Credits

Based on [AutoVirt](https://github.com/Scrut1ny/AutoVirt).
