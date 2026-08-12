<div align="center">

# VMW - VM Workspace

Automated Linux virtualization setup for an undetected VM: patched QEMU, EDK2/OVMF, kernel, VFIO passthrough, and SMBIOS spoofing.

Based on [AutoVirt](https://github.com/Scrut1ny/AutoVirt).

</div>

---

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

Each VM is one YAML file in `configs/` (`configs/vmud.yml` is the default profile). Values in the profile replace the interactive prompts; omit a value to fall back to the prompt.

`python/vmw/genxml.py` turns the profile into a libvirt domain XML, validated against the libvirt schema before `virsh define`.

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

Every patch under `patches/` is SHA256-verified against `patches/checksums.sha256` and stamped with its target source version. To add or update a patch:

```sh
scripts/add_patch.sh patches/QEMU/AMD-v11.0.4.patch v11.0.4
vmw patch-status
```

### Verify patches apply cleanly

`vmw patch-check` clones each source repo at the stamped version (QEMU tag, EDK2 tag with submodules, upstream Linux tag) and runs `git apply --check` on every active patch. It does not apply anything. Run it before a long build to catch broken or stale patches.

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

## Troubleshooting

#### QEMU log
```
vfio 0000:01:00.0: failed to setup container for group 13: Failed to set group container: Invalid argument
```
#### dmesg log
```
vfio-pci 0000:01:00.0: Firmware has requested this device have a 1:1 IOMMU mapping, rejecting configuring the device without a 1:1 mapping. Contact your platform vendor.
```

- Disable `Pre-boot DMA Protection` (needed for VFIO)
  - Change `IOMMU` from `[Auto]` to `[Enabled]` to find the hidden setting.
