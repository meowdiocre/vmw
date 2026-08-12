#!/usr/bin/env bash

# VMW — VM Workspace
# CLI entrypoint + interactive menu.
#
# Usage:
#   ./main.sh                     interactive menu
#   ./main.sh plan <profile>      dry-run all modules for a profile
#   ./main.sh setup <profile>     run the full setup for a profile
#   ./main.sh deploy <profile>    generate + define the domain XML
#   ./main.sh patch-status        verify patch checksums + versions
#   ./main.sh status              show VMs and profile state

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

source ./utils.sh || { echo "Failed to load utilities module!"; exit 1; }

usage() {
    cat <<'EOF'
VMW — VM Workspace

Usage:
  ./main.sh                     Interactive menu
  ./main.sh plan <profile>      Dry-run all modules (print commands)
  ./main.sh setup <profile>     Run the full automated setup
  ./main.sh deploy <profile>    Generate + define the domain XML
  ./main.sh patch-status        Verify patch integrity + target versions
  ./main.sh status              Show VMs and profile state
  ./main.sh help                Show this help
EOF
}

cmd_plan() {
    local profile=$1
    vmw::load_config "$profile" || return 1
    fmtr::box_text "PLAN: $profile"
    vmw::verify_patches
    echo ""
    fmtr::info "The following would be executed for profile '$profile':"
    echo ""
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Install virt packages (dnsmasq libvirt virt-manager swtpm qemu-base)"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Configure user groups + libvirt + AutoVirt-Router network"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Clone + patch QEMU $CFG_PATCHES_QEMU → /opt/AutoVirt/emulator"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Clone + patch EDK2 $CFG_PATCHES_EDK2 → /opt/AutoVirt/firmware"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "VFIO passthrough config (IOMMU, vfio-pci)"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Kernel build with $CFG_PATCHES_KERNEL via linux-tkg (~35GB, -j1)"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Looking Glass setup"
    printf '  %b·%b %s\n' "$TEXT_BRIGHT_GREEN" "$RESET" "Generate + define domain XML for $profile (see below)"
    echo ""
    fmtr::info "Generated domain XML (dry-run):"
    python3 "$(pwd)/resources/generate_xml.py" "$profile"
}

cmd_setup() {
    local profile=$1
    vmw::load_config "$profile" || return 1
    fmtr::box_text "SETUP: $profile"
    vmw::verify_patches || { fmtr::error "Patch verification failed. Run './main.sh patch-status'."; return 1; }
    for mod in virtualization qemu edk2 vfio kernel lg deploy; do
        fmtr::info "[$mod] running..."
        ./modules/"$mod".sh || { fmtr::error "[$mod] failed."; return 1; }
    done
    fmtr::log "Setup complete for profile '$profile'."
}

cmd_deploy() {
    local profile=$1
    ./modules/deploy.sh "$profile"
}

cmd_patch_status() {
    python3 "$(pwd)/scripts/vmw_patches.py" verify
}

cmd_status() {
    fmtr::box_text "VMW STATUS"
    echo ""
    fmtr::info "Config profiles:"
    for f in configs/*.yml; do
        [[ -e $f ]] || continue
        printf '  %s\n' "$(basename "$f")"
    done
    echo ""
    fmtr::info "Libvirt domains:"
    $ROOT_ESC virsh list --all 2>/dev/null || fmtr::error "Cannot list VMs (libvirt not reachable?)"
    echo ""
    if [[ -f .vmw/state.json ]]; then
        fmtr::info "State manifest:"
        python3 "$(pwd)/scripts/vmw_state.py" list
    fi
}

main_menu() {
    local menu=(
        "Virtualization Setup|virtualization.sh"
        "QEMU (Patched) Setup|qemu.sh"
        "EDK2 (Patched) Setup|edk2.sh"
        "GPU Passthrough Setup|vfio.sh"
        "Kernel (Patched) Setup|kernel.sh"
        "Looking Glass Setup|lg.sh"
        "Deploy VM from profile|deploy.sh"
    )

    trap '
        clear & echo
        if prmt::yes_or_no "$(fmtr::ask "Do you want to clear the logs directory?")"; then
            rm -f -- "${LOG_PATH}"/*.log
        fi
        exit 0
    ' INT

    while :; do
        clear
        fmtr::box_text " >> VMW << "; echo ""

        for i in "${!menu[@]}"; do
            printf '  %b[%d]%b %s\n' \
                "$TEXT_BRIGHT_YELLOW" "$((i+1))" "$RESET" "${menu[i]%%|*}"
        done
        echo
        printf '  %b[8]%b Plan (dry-run)\n' "$TEXT_BRIGHT_YELLOW" "$RESET"
        printf '  %b[9]%b Status\n' "$TEXT_BRIGHT_YELLOW" "$RESET"
        echo

        local choice
        choice="$(prmt::quick_prompt '  Enter your choice [1-9]: ')" || continue
        clear

        case "$choice" in
            8) cmd_plan "${CONFIG_PROFILE:-aptwannabe}";;
            9) cmd_status;;
            *)
                if (( choice >= 1 && choice <= ${#menu[@]} )); then
                    local idx=$((choice - 1))
                    local label="${menu[idx]%%|*}"
                    local script="${menu[idx]#*|}"
                    fmtr::box_text "$label"
                    if [[ -n "$script" ]]; then
                        if [[ "$script" == "deploy.sh" ]]; then
                            ./modules/deploy.sh "${CONFIG_PROFILE:-aptwannabe}"
                        else
                            ./modules/"$script"
                        fi
                    else
                        fmtr::warn "This module isn't ready yet."
                    fi
                else
                    fmtr::error "Invalid option, please try again."
                fi
                ;;
        esac

        prmt::quick_prompt "$(fmtr::info 'Press any key to continue...')"
    done
}

cmd="${1:-menu}"
case "$cmd" in
    menu|"") main_menu ;;
    plan) shift; cmd_plan "${1:-aptwannabe}" ;;
    setup) shift; cmd_setup "${1:-aptwannabe}" ;;
    deploy) shift; cmd_deploy "${1:-aptwannabe}" ;;
    patch-status) cmd_patch_status ;;
    status) cmd_status ;;
    help|-h|--help) usage ;;
    *) fmtr::error "Unknown command: $cmd"; echo; usage; exit 1 ;;
esac
