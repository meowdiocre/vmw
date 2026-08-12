#!/usr/bin/env bash
# Host detection: Linux distribution and CPU vendor.
#
# Sets DISTRO (Arch/Debian/openSUSE/Fedora) and CPU_* variables used by
# the package installer and kernel/qemu/edk2 patch selection.
#
# Requires: lib/env.sh, lib/log.sh.

vmw::detect_distro() {
    local id=""
    if [[ -r /etc/os-release ]]; then
        . /etc/os-release
        id="$(prmt::lower "${ID:-}")"
    fi

    if [[ $id =~ ^(arch|manjaro|endeavouros|arcolinux|garuda|artix)$ ]] ||
       { command -v pacman >/dev/null 2>&1 && [[ -d /etc/pacman.d ]]; }; then
        DISTRO="Arch"
    elif [[ $id =~ ^(opensuse|sles|opensuse-tumbleweed|opensuse-leap)$ ]] ||
         { command -v zypper >/dev/null 2>&1; }; then
        DISTRO="openSUSE"
    elif [[ $id =~ ^(fedora|centos|rhel|rocky|alma|oracle)$ ]] ||
         { command -v dnf >/dev/null 2>&1; }; then
        DISTRO="Fedora"
    elif [[ $id =~ ^(debian|ubuntu|linuxmint|kali|pop|elementary|zorin|mx|parrot|deepin|peppermint)$ ]] ||
         { command -v apt >/dev/null 2>&1; }; then
        DISTRO="Debian"
    else
        fmtr::fatal "Unsupported distribution: ${id:-unknown}."
        exit 1
    fi

    export DISTRO
    readonly DISTRO
}

vmw::detect_cpu() {
    local line
    while IFS= read -r line; do
        case "$line" in
            *GenuineIntel*)
                CPU_VENDOR_ID="GenuineIntel"
                CPU_VIRTUALIZATION="vmx"
                CPU_MANUFACTURER="Intel"
                break
                ;;
            *AuthenticAMD*)
                CPU_VENDOR_ID="AuthenticAMD"
                CPU_VIRTUALIZATION="svm"
                CPU_MANUFACTURER="AMD"
                break
                ;;
        esac
    done < /proc/cpuinfo

    if [[ -z $CPU_VENDOR_ID ]]; then
        fmtr::fatal "Unsupported CPU vendor."
        exit 1
    fi

    export CPU_VENDOR_ID CPU_VIRTUALIZATION CPU_MANUFACTURER
    readonly CPU_VENDOR_ID CPU_VIRTUALIZATION CPU_MANUFACTURER
}

vmw::detect_host() {
    vmw::detect_distro
    vmw::detect_cpu
}
