#!/usr/bin/env bash
# Package installation helpers (distro-aware).
#
# Requires: lib/env.sh, lib/log.sh, lib/log_init.sh (ROOT_ESC), lib/prompt.sh.
# Modules define REQUIRED_PKGS_<Distro> arrays before calling.

install_req_pkgs() {
    local component=$1
    [[ -n $component ]] || { fmtr::error "Component name not specified!"; exit 1; }

    fmtr::log "Checking for required missing $component packages..."

    local mgr install_flags check_cmd
    case $DISTRO in
      Arch)     mgr=pacman; install_flags='-S --noconfirm'; check_cmd='pacman -Q' ;;
      Debian)   mgr=apt;    install_flags='-y install';     check_cmd='dpkg -s'   ;;
      openSUSE) mgr=zypper; install_flags='install -y';     check_cmd='rpm -q'    ;;
      Fedora)   mgr=dnf;    install_flags='-yq install';    check_cmd='rpm -q'    ;;
      *) fmtr::error "Unsupported distribution: $DISTRO."; exit 1 ;;
    esac

    local pkg_var="REQUIRED_PKGS_${DISTRO}"
    declare -n req="$pkg_var" 2>/dev/null || { fmtr::error "$component packages undefined for $DISTRO."; exit 1; }

    local -a missing=()
    local pkg
    for pkg in "${req[@]}"; do
      $check_cmd "$pkg" &>/dev/null || missing+=("$pkg")
    done

    (( ${#missing[@]} )) || { fmtr::log "All required $component packages already installed."; return 0; }

    fmtr::warn "Missing required $component packages: ${missing[*]}"
    if prmt::yes_or_no "$(fmtr::ask_inline "Install required missing $component packages?")"; then
      $ROOT_ESC "$mgr" $install_flags "${missing[@]}" &>>"$LOG_FILE" || { fmtr::error "Failed to install required $component packages"; exit 1; }
      fmtr::log "Installed: ${missing[*]}"
    else
      fmtr::log "Exiting due to required missing $component packages."
      exit 1
    fi
}
