<div align="center">

# VMW — VM Workspace

A personal VM workspace for automating Linux virtualization setup, focused on building an undetected VM (patched QEMU, EDK2/OVMF, kernel, VFIO, SMBIOS spoofing).

Mainly taken from [AutoVirt](https://github.com/Scrut1ny/AutoVirt)

</div>

---

## Quick start

```sh
git clone --single-branch --depth=1 https://github.com/meowdiocre/vmw
cd vmw/

./main.sh plan aptwannabe      # review what will happen (no execution)
./main.sh setup aptwannabe     # run the full automated setup
```

Or run the interactive menu:

```sh
./main.sh
```

## CLI

```
vmw                          Interactive menu
vmw plan <profile>           Dry-run all modules (print commands)
vmw setup <profile>          Run the full automated setup
vmw deploy <profile>         Generate + define the domain XML
vmw patch-status             Verify patch integrity + target versions
vmw status                   Show VMs and profile state
vmw help                     Show this help
```

`./main.sh` is a thin wrapper around `bin/vmw`.

## Configuration

Each VM is described by a declarative YAML profile in `configs/` (e.g. `configs/aptwannabe.yml`). Values in the profile replace interactive prompts; omit a value to fall back to the prompt in menu mode.

Domain XML is generated deterministically from the profile by `python/vmw/genxml.py` and schema-validated before `virsh define`. See `docs/PLAN.md` for the full architecture and phase-by-phase breakdown.

## Project layout

```
vmw/
├── bin/vmw            CLI entrypoint (menu + subcommands)
├── lib/               shared bash libraries (colors, log, prompt, config,
│                      state, run, packages, patches) — loaded via lib/init.sh
├── modules/           per-feature scripts (virtualization, qemu, edk2,
│                      vfio, kernel, lg, deploy)
├── python/vmw/        Python tooling package (yaml, state, patches, genxml)
├── configs/           per-VM YAML profiles
├── patches/           versioned patch artifacts + checksums.sha256
├── resources/         helper scripts (SMBIOS, vbios dumpers, ...)
├── scripts/           dev workflows (add_patch.sh)
├── docs/              design docs
├── .vmw/              local state (gitignored)
├── logs/              runtime logs (gitignored)
└── src/               build artifacts (gitignored)
```

## Patches

Patches are versioned artifacts under `patches/`, verified by SHA256 checksums and stamped with their target source version. Add or update a patch with:

```sh
scripts/add_patch.sh patches/QEMU/AMD-v11.0.4.patch v11.0.4
vmw patch-status
```

## Prerequisites

- `git`, `python3` + `pyyaml` + `lxml`
- Supported Linux distribution
- UEFI/BIOS Settings:
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

- Disable `Pre-boot DMA Protection` (Needed for VFIO)
  - (*Change `IOMMU` from `[Auto]` to `[Enabled]` to find hidden setting*)
