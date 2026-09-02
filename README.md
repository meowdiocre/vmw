<div align="center">


![idk why i use bmw logo](./static/m.png)
# VMW

**A specialized virtual machine workspace setup designed for researching edge technology and virtualization features on Windows.**

Automates the build and management of a KVM guest running Windows, fully configured for Hyper-V, HVCI, nested virtualization, GPU passthrough, or performance-optimized bare-metal CPUID passthrough.

*Currently tested exclusively on AMD CPU architectures.*</div>

---

## Description

**VMW** turns one YAML profile into a full virtualization stack a
custom kernel, a custom QEMU, custom OVMF firmware, and a libvirt
domain definition. Each layer has a patch set under `patches/`. The
patches change the values that guest software can read: CPUID leaves,
MSR behavior, firmware tables, SMBIOS strings, and TPM identity.

The research target is
[VMAware](https://github.com/kernelwernel/VMAware), an open-source
VM-detection library.  and other ring-0 checks

## Quick start

```sh
git clone --single-branch --depth=1 https://github.com/meowdiocre/vmw
cd vmw/
pip install -e .           # installs the `vmw` command

vmw                        # launch the dashboard TUI
vmw plan aptwannabe        # review what a setup would run, execute nothing
vmw setup aptwannabe       # run the full build headless
```

## Documentation

This README covers what the project is. Everything else lives on the
[documentation site](https://meowdiocre.github.io/vmw/), built from
`docs/`:

- **Usage** :  CLI commands, profile format, patch workflow.
- **QEMU / Firmware / TPM / Kernel** 
  why.
- **Operations** : VM profile notes, known gaps, useful commands.
- **Roadmap** : current detection status.

## Prerequisites

- `git`, `python3` (3.11+); `pip install -e .` pulls the rest
- A supported Linux distribution
- UEFI/BIOS settings: CPU virtualization extensions (VT-x / AMD-V),
  IOMMU support (VT-d / AMD-Vi)
- A dGPU for passthrough (recommended)

## Credits

Based on [AutoVirt](https://github.com/Scrut1ny/AutoVirt).

## License

GPL-3.0-or-later.
