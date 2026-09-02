# Operations

## VM profile notes (`configs/aptwannabe.yml`)

- CPU: `host-passthrough`, `check='none'`, `migratable='off'`,
  topology 1 socket / 4 cores / 2 threads. Both 4c/2t and 8c/1t boot;
  4c/2t is the current setting.
- `nrip` is unknown to libvirt 12.5 and must stay out of the SVM
  feature list.
- `<kvm><hidden state='on'/></kvm>` hides the hypervisor bit from
  the guest's own CPUID view.
- `hypervclock` timer is present.
- Networking: DHCP hands out `192.168.122.85` (hostname
  `DESKTOP-FNKT0LT`, MAC 52:54:00:e1:1a:96). RDP (3389) and msrpc
  (135) are open; ICMP is blocked by the guest firewall. Lease file:
  `/var/lib/libvirt/dnsmasq/virbr0.status`.

## Known gap: deploy does not capture every manual change

The domain XML generator (`python/vmw/genxml/`) emits the `-smbios`
argument under `qemu:commandline` but not the ACPI table arguments,
the full machine argument string, or GPU passthrough `hostdev`
entries — those are added to the live domain by hand after `vmw
deploy` runs. Running `vmw setup <profile>` on a fresh machine
produces a VM that boots but is missing the fake battery table, the
custom device tables, and the tuned machine arguments, several of
which close detections listed in
[Kernel: what it patches](kernel/index.md#what-it-patches). Closing
this gap means teaching `genxml/` to emit `-acpitable` and arbitrary
machine arguments from the profile, plus an install step that copies
the `.aml` files into `/opt/vmw/firmware/`.

## Useful commands

```bash
# sudo (password read into $VMW_SUDO once per shell, never stored)
read -rs VMW_SUDO
echo "$VMW_SUDO" | sudo -S <command>

# Start the VM / reload kvm_amd if it did not autoload
echo "$VMW_SUDO" | sudo -S virsh --connect qemu:///system start aptwannabe
echo "$VMW_SUDO" | sudo -S modprobe kvm_amd

# Rebuild the kernel (ccache configured: ~5-10 min instead of ~60)
cd src/linux-tkg
git -C linux-src-git reset --hard && git -C linux-src-git clean -ffdx
rm -f *.pkg.tar.zst
setsid nohup makepkg -sf --noconfirm > /tmp/kernel-build.log 2>&1 < /dev/null &
# then: pacman -U both built packages (dkms hooks take ~5 min), then reboot

# Regenerate patches/checksums.sha256 after editing a patch
PYTHONPATH="$PWD/python" python3 -m vmw.patches gen

# Watch the guest for a frozen-RIP boot hang (one vCPU pinned near 100%)
echo "$VMW_SUDO" | sudo -S virsh --connect qemu:///system qemu-monitor-command \
  aptwannabe '{"execute":"human-monitor-command","arguments":{"command-line":"info registers"}}'
```

Rebuild OVMF directly, without the interactive module, when the
source tree already has the patch applied:

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

# Check the FV bases landed where expected, then install
grep _PCD_VALUE_PcdOvmfPeiMemFvBase \
  Build/OvmfX64/RELEASE_GCC/X64/OvmfPkg/Sec/SecMain/DEBUG/AutoGen.h
echo "$VMW_SUDO" | sudo -S cp -a /opt/vmw/firmware/OVMF_CODE.fd \
                            /opt/vmw/firmware/OVMF_CODE.fd.bak
echo "$VMW_SUDO" | sudo -S cp Build/OvmfX64/RELEASE_GCC/FV/OVMF_CODE.fd \
                         /opt/vmw/firmware/OVMF_CODE.fd
```

Running `steps/edk2.py` instead re-runs the full flow, including a
prompt to purge and re-clone the source tree; answer "no" to keep the
patched tree.

Reference points:

- Build-tree copy of the kernel patch, kept in sync with
  `patches/Kernel/amd702.mypatch`:
  `src/linux-tkg/linux70-tkg-userpatches/amd702.mypatch`
- Kernel source worktree: `src/linux-tkg/linux-src-git`
- Custom QEMU binary: `/opt/vmw/emulator/bin/qemu-system-x86_64`
- Firmware: `/opt/vmw/firmware/` (`OVMF_CODE.fd`, `OVMF_VARS.fd`,
  `smbios.bin`, `fake_battery.aml`, `spoofed_devices.aml`,
  `vbios.rom`)
- Full VM XML: `virsh --connect qemu:///system dumpxml aptwannabe`
