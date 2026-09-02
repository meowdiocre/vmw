# vmw

vmw turns one YAML profile into a full KVM virtualization stack: a
patched kernel, a patched QEMU, patched OVMF firmware, and a libvirt
domain definition. Each layer changes values that guest software can
read: CPUID leaves, MSR behavior, firmware tables, SMBIOS strings,
and TPM identity.

The research target is [VMAware](https://github.com/kernelwernel/VMAware),
an open-source VM-detection library. [Research](qemu/index.md) covers
which detection surfaces close, and which are inherent to nested
virtualization.

## Quickstart

```console
$ git clone https://github.com/meowdiocre/vmw.git
$ cd vmw
$ pip install -e ".[dev]"
$ vmw
```

`vmw` with no arguments opens the dashboard TUI. See
[Usage](usage.md) for the full CLI.

## Layout

| Section | Covers |
|---|---|
| [Usage](usage.md) | CLI commands, profile format, patch workflow |
| [QEMU](qemu/index.md) | Hypervisor CPUID bits, ACPI tables, SMBIOS |
| [Firmware](firmware/index.md) | OVMF build, boot logo, secure boot, identity strings |
| [TPM](tpm/index.md) | libtpms and swtpm identity |
| [Kernel](kernel/index.md) | The KVM/SVM patch: CPUID interception, MSR passthrough |
| [Operations](operations.md) | Running profile, known gaps, useful commands |
| [Manual scripts](scripts.md) | Host/guest setup scripts vmw does not automate |
| [Roadmap](roadmap.md) | Current detection status |

## Status

The refactor is in progress on the `refactor` branch. See the
[roadmap](roadmap.md) for current status.

## License

GPL-3.0-or-later. See [the repository](https://github.com/meowdiocre/vmw).
