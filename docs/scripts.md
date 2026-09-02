# Manual scripts

`resources/scripts/` holds standalone host- and guest-side scripts.
`vmw` does not run these automatically; run each one by hand when its
situation applies. `resources/scripts/Linux/SMBIOS.py` is the one
exception — `steps/qemu.py` calls it directly to build `smbios.bin`.

## Linux (host side)

### `vbios-dumper.sh`

Dumps the GPU's video BIOS from sysfs: unbinds the current driver,
enables the ROM read at `/sys/bus/pci/devices/<BDF>/rom`, copies it
out, disables the ROM read, and rebinds the driver. The PCI address
is hardcoded to `0000:01:00.0` at the top of the script — edit it to
match your GPU (`lspci` shows the address). The dumped `.rom` file is
what a passthrough profile points to when a card needs a vBIOS to
avoid Code 43.

### `vbios-dumper-safe.sh`

Same purpose as `vbios-dumper.sh`, hardened for laptop GPUs, which
can hang on an unbind or a ROM read. It adds timeouts on both steps,
checks the dump size before accepting it, rebinds the driver on any
failure, and prints the file's first bytes so you can confirm the
dump is a real VBIOS and not empty or truncated. Prefer this version
on a laptop; use `vbios-dumper.sh` on a desktop where the plain
version is faster.

### `evdev-auto.sh`

Detects physical keyboard and mouse devices under
`/dev/input/by-id/` and `/dev/input/by-path/`, deduplicates them by
real path, and prints a libvirt `<input type="evdev">` block for
each — for a single-GPU passthrough setup that switches keyboard and
mouse into the guest with a hotkey (`shift-shift` by default). Paste
the output into the domain XML's `<devices>` section.

### `arch_kernel_downgrade.sh`

Installs Linux `6.10.arch1-2` and its headers from the Arch Linux
Archive, pins the kernel package in `pacman.conf` with `IgnorePkg`
so a routine `pacman -Syu` does not upgrade past it, rebuilds the
initramfs, and reboots. Use this to roll back to a known-good kernel
version when a newer one regresses a build or breaks guest boot. Edit
the package version at the top of the script to target a different
kernel release.

## Windows (guest side)

### `EDID_OVERRIDE.ps1`

Run as Administrator inside the guest. Reads each connected
monitor's real EDID over WMI, zeroes the manufacturer serial-number
field and any monitor-serial-number descriptor block, recomputes the
EDID checksum, and writes the modified EDID into that monitor's
`EDID_OVERRIDE` registry key. Restarts the display drivers so
Windows picks up the new EDID immediately.

### `qemu-cleanup.ps1`

Run inside the guest. Downloads Sysinternals PSTools if not already
present, then uses PsExec to run a cleanup step as SYSTEM that scans
`HKLM\SYSTEM\CurrentControlSet\Enum` for device entries matching
VirtIO PCI identifiers (`VEN_1AF4`, `DEV_1B36`, `SUBSYS_11001AF4`)
and deletes them, and removes every subkey under `Enum\SCSI`. Use
this after removing or replacing a VirtIO device, so Windows' device
history does not keep an entry for hardware that is no longer
present — a stale entry there is a difference from a physical
machine that a careful check could otherwise read.
