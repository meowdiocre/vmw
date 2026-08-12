#!/usr/bin/env bash
# Real-system probes: detect whether a setup step is already in place.
#
# Returns 0 if the step is done, 1 if not. This complements the local
# state manifest (.vmw/state.json): the manifest tracks what this repo ran,
# while these probes check the actual machine (kernel, binaries, services).
#
# Requires: lib/env.sh, lib/init.sh (ROOT_ESC, DISTRO).

Vmw_OUT_DIR="/opt/vmw"

vmw::step_ready() {
    local step=$1
    case "$step" in
        virtualization)
            # libvirt running and the vmw-Router network present.
            if systemctl is-active --quiet libvirtd 2>/dev/null ||
               systemctl is-active --quiet virtqemud 2>/dev/null; then
                $ROOT_ESC virsh net-info vmw-Router >/dev/null 2>&1 && return 0
            fi
            return 1
            ;;

        kernel)
            # The patched kernel tag is installed and a boot entry exists.
            local kernel_tag="linux${KERNEL_MAJOR}${KERNEL_MINOR}-tkg-eevdf"
            if [[ -e "/boot/vmlinuz-$kernel_tag" ]]; then
                return 0
            fi
            local entry_dir
            for entry_dir in "/boot/loader/entries" "/boot/efi/loader/entries" "/efi/loader/entries"; do
                if [[ -d "$entry_dir" && -f "$entry_dir/HvP-RDTSC.conf" ]]; then
                    return 0
                fi
            done
            return 1
            ;;

        qemu)
            # Patched QEMU binary installed.
            [[ -x "$Vmw_OUT_DIR/emulator/bin/qemu-system-x86_64" ]] && return 0
            return 1
            ;;

        edk2)
            # Patched OVMF firmware installed.
            if [[ -f "$Vmw_OUT_DIR/firmware/OVMF_CODE.fd" && -f "$Vmw_OUT_DIR/firmware/OVMF_VARS.fd" ]]; then
                return 0
            fi
            return 1
            ;;

        vfio)
            # A PCI device is bound to vfio-pci (IOMMU/passthrough active).
            if [[ -d /sys/kernel/iommu_groups && -d /sys/bus/pci/drivers/vfio-pci ]]; then
                if ls /sys/bus/pci/drivers/vfio-pci/ 2>/dev/null | grep -qE '^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.'; then
                    return 0
                fi
            fi
            # Fallback: vfio-pci loaded with a driver override configured.
            grep -qw vfio-pci /proc/modules 2>/dev/null && return 0
            return 1
            ;;

        deploy)
            # The domain from the profile is defined in libvirt.
            local domain="${CONFIG_PROFILE:-vmud}"
            $ROOT_ESC virsh dominfo "$domain" >/dev/null 2>&1 && return 0
            return 1
            ;;

        *) return 1 ;;
    esac
}

# Combined check: state manifest OR real system probe.
vmw::step_done_p() {
    if vmw::state has "module.$1.complete"; then
        return 0
    fi
    vmw::step_ready "$1"
}
