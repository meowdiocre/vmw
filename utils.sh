#!/usr/bin/env bash

# =============================================================================
# ANSI ESCAPE CODES - Text Styles, Colors, Backgrounds
# =============================================================================

# Styles
readonly RESET=$'\033[0m'
readonly TEXT_BOLD=$'\033[1m'
readonly TEXT_DIM=$'\033[2m'
readonly TEXT_ITALIC=$'\033[3m'
readonly TEXT_UNDER=$'\033[4m'
readonly TEXT_BLINK=$'\033[5m'
readonly TEXT_REVERSE=$'\033[7m'
readonly TEXT_HIDDEN=$'\033[8m'
readonly TEXT_STRIKE=$'\033[9m'

# Foreground colors
readonly TEXT_BLACK=$'\033[30m'       TEXT_GRAY=$'\033[90m'
readonly TEXT_RED=$'\033[31m'         TEXT_BRIGHT_RED=$'\033[91m'
readonly TEXT_GREEN=$'\033[32m'       TEXT_BRIGHT_GREEN=$'\033[92m'
readonly TEXT_YELLOW=$'\033[33m'      TEXT_BRIGHT_YELLOW=$'\033[93m'
readonly TEXT_BLUE=$'\033[34m'        TEXT_BRIGHT_BLUE=$'\033[94m'
readonly TEXT_MAGENTA=$'\033[35m'     TEXT_BRIGHT_MAGENTA=$'\033[95m'
readonly TEXT_CYAN=$'\033[36m'        TEXT_BRIGHT_CYAN=$'\033[96m'
readonly TEXT_WHITE=$'\033[37m'       TEXT_BRIGHT_WHITE=$'\033[97m'

# Background colors
readonly BACK_BLACK=$'\033[40m'       BACK_GRAY=$'\033[100m'
readonly BACK_RED=$'\033[41m'         BACK_BRIGHT_RED=$'\033[101m'
readonly BACK_GREEN=$'\033[42m'       BACK_BRIGHT_GREEN=$'\033[102m'
readonly BACK_YELLOW=$'\033[43m'      BACK_BRIGHT_YELLOW=$'\033[103m'
readonly BACK_BLUE=$'\033[44m'        BACK_BRIGHT_BLUE=$'\033[104m'
readonly BACK_MAGENTA=$'\033[45m'     BACK_BRIGHT_MAGENTA=$'\033[105m'
readonly BACK_CYAN=$'\033[46m'        BACK_BRIGHT_CYAN=$'\033[106m'
readonly BACK_WHITE=$'\033[47m'       BACK_BRIGHT_WHITE=$'\033[107m'

# =============================================================================
# LOGGING (low-level)
# =============================================================================

__log::write() {
    local stream=$1; shift
    if [[ $stream == stderr ]]; then
      printf '%b\n' "$*" >&2
    else
      printf '%b\n' "$*"
    fi
    printf '%b\n' "$*" >>"$LOG_FILE"
}

# =============================================================================
# FORMAT / LOG HELPERS
# =============================================================================

__fmtr::line() {
    local icon=$1 color=$2; shift 2
    printf '\n  %b%s%b %s' "$color" "$icon" "$RESET" "$*"
}

fmtr::log()   { __log::write stdout "$(__fmtr::line '[+]' "$TEXT_BRIGHT_GREEN"  "$@")"; }
fmtr::info()  { __log::write stdout "$(__fmtr::line '[i]' "$TEXT_BRIGHT_CYAN"   "$@")"; }
fmtr::warn()  { __log::write stdout "$(__fmtr::line '[!]' "$TEXT_BRIGHT_YELLOW" "$@")"; }
fmtr::error() { __log::write stderr "$(__fmtr::line '[-]' "$TEXT_BRIGHT_RED"    "$@")"; }

fmtr::fatal() {
    __log::write stderr "$(printf '\n  %b%s %s%b' "$TEXT_RED$TEXT_BOLD" '[X]' "$*" "$RESET")"
}

fmtr::box_text() {
    local text=$1 pad border
    printf -v pad '%*s' $(( ${#text} + 2 )) ''
    border=${pad// /═}
    printf '\n  ╔%s╗\n  ║ %s ║\n  ╚%s╝\n' "$border" "$text" "$border"
}

fmtr::ask() {
    __log::write stdout "$(printf '\n  %b[?]%b %s' "$TEXT_BLACK$BACK_BRIGHT_GREEN" "$RESET" "$1")"
}

fmtr::ask_inline() {
    printf '\n  %b[?]%b %s' "$TEXT_BLACK$BACK_BRIGHT_GREEN" "$RESET" "$1"
}

# =============================================================================
# PROMPTS
# =============================================================================

prmt::yes_or_no() {
    local prompt=$* ans
    while :; do
      read -rp "$prompt [y/n]: " ans
      printf '%s\n' "$ans" >>"$LOG_FILE"
      case ${ans,,} in
        y*) return 0 ;;
        n*) return 1 ;;
        *)  printf '\n  [!] Please answer y/n\n' ;;
      esac
    done
}

prmt::quick_prompt() {
    local response
    read -n1 -srp "$1" response
    printf '%s\n' "$response"
    printf '%s\n' "$response" >>"$LOG_FILE"
}

# =============================================================================
# DEBUG
# =============================================================================

dbg::fail() { fmtr::fatal "$1"; exit 1; }

# =============================================================================
# COMPATIBILITY
# =============================================================================

# Sets $ROOT_ESC to the first available privilege escalation tool (sudo, doas, pkexec).
compat::get_escalation_cmd() {
    local cmd
    for cmd in sudo doas pkexec; do
      if command -v -- "$cmd" &>/dev/null; then
        ROOT_ESC=$cmd
        export ROOT_ESC
        return 0
      fi
    done

    fmtr::error "No supported privilege escalation tool found (sudo/doas/pkexec)."
    exit 1
}

# =============================================================================
# PACKAGES
# =============================================================================

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

# =============================================================================
# LOGGING (init / side-effects)
# =============================================================================

log::init() {
    : "${LOG_PATH:=$(pwd)/logs}"
    : "${LOG_FILE:=$LOG_PATH/$(date +%s).log}"

    export LOG_PATH LOG_FILE
    mkdir -p -- "$LOG_PATH" || { printf 'Failed to create log directory.\n' >&2; exit 1; }
    : >"$LOG_FILE"          || { printf 'Failed to create log file.\n' >&2; exit 1; }
}

# =============================================================================
# CONFIG (YAML profiles)
# =============================================================================

# Loads a configs/<profile>.yml profile into CFG_* variables.
#   vmw::load_config <profile>   # e.g. aptwannabe (no .yml suffix)
# Returns 0 on success, 1 if the profile doesn't exist.
vmw::load_config() {
    local profile=$1
    [[ -n $profile ]] || profile="aptwannabe"
    CONFIG_PROFILE="$profile"
    CONFIG_FILE="$(pwd)/configs/${profile}.yml"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        fmtr::error "Config profile '$profile' not found at $CONFIG_FILE"
        return 1
    fi

    local cfg_script
    cfg_script="$(python3 "$(pwd)/scripts/vmw_yaml.py" "$CONFIG_FILE")" || {
        fmtr::error "Failed to parse YAML profile '$profile'."
        return 1
    }

    # Clear any previously loaded CFG_* values
    unset CFG_NAME CFG_VM_MEMORY_MIB CFG_VM_VCPUS CFG_VM_OSINFO \
          CFG_CPU_TOPOLOGY_SOCKETS CFG_CPU_TOPOLOGY_CORES CFG_CPU_TOPOLOGY_THREADS \
          CFG_CPU_CHECK CFG_CPU_MIGRATABLE CFG_CPU_CACHE CFG_CPU_MAXPHYSADDR \
          CFG_BOOT_ORDER CFG_BOOT_MENU CFG_BOOT_LOADER CFG_BOOT_LOADER_SECURE CFG_BOOT_NVRAM_TEMPLATE \
          CFG_FEATURES_HYPERV CFG_FEATURES_KVM_HIDDEN CFG_FEATURES_PMU CFG_FEATURES_VMPORT \
          CFG_FEATURES_SMM CFG_FEATURES_MSRS_UNKNOWN CFG_FEATURES_PS2 \
          CFG_HYPERV_MODE CFG_HYPERV_RELAXED CFG_HYPERV_VAPIC CFG_HYPERV_SPINLOCKS \
          CFG_HYPERV_SPINLOCKS_RETRIES CFG_HYPERV_VENDOR_ID_STATE CFG_HYPERV_VENDOR_ID \
          CFG_CLOCK_OFFSET CFG_CLOCK_TSC_PRESENT CFG_CLOCK_TSC_MODE CFG_CLOCK_KVMCLOCK_PRESENT \
          CFG_CLOCK_HYPERVCLOCK_PRESENT CFG_PM_SUSPEND_TO_MEM CFG_PM_SUSPEND_TO_DISK \
          CFG_DEVICE_EMULATOR CFG_DEVICE_DISK_SIZE_GB CFG_DEVICE_DISK_BUS CFG_DEVICE_DISK_CACHE \
          CFG_DEVICE_DISK_IO CFG_DEVICE_DISK_BLOCK_LOGICAL CFG_DEVICE_DISK_BLOCK_PHYSICAL \
          CFG_DEVICE_NIC_MODEL CFG_DEVICE_SOUND_MODEL CFG_DEVICE_AUDIO_TYPE CFG_DEVICE_GRAPHICS \
          CFG_DEVICE_VIDEO CFG_DEVICE_TPM CFG_DEVICE_TPM_MODEL CFG_DEVICE_MEMBALLOON \
          CFG_PATHS_DOWNLOADS_DIR CFG_PATHS_ISO_PATH \
          CFG_PATCHES_KERNEL CFG_PATCHES_QEMU CFG_PATCHES_EDK2 \
          CFG_EVDEV_ENABLED CFG_EVDEV_GRAB_TOGGLE \
          CFG_AUDIO_PIPEWIRE CFG_AUDIO_MIXING_ENGINE 2>/dev/null || true

    eval "$cfg_script"

    export CONFIG_PROFILE CONFIG_FILE
    fmtr::info "Loaded config profile: $profile"
    return 0
}

# Returns the value of a CFG_* variable (string), or empty string if unset.
#   vmw::cfg <path>   # e.g. vm.memory_mib
vmw::cfg() {
    local key="CFG_${1//./_}"
    key="${key//-/_}"
    if [[ $BASH_VERSION ]]; then
        printf '%s' "${!key-}"
    else
        # zsh indirect expansion
        printf '%s' "${(P)key:-}"
    fi
}

# Returns 0 (true) if the given config path is set and non-empty.
vmw::has_cfg() {
    local val
    val="$(vmw::cfg "$1")"
    [[ -n $val ]]
}

# =============================================================================
# STATE MANIFEST (idempotency / resume)
# =============================================================================

vmw::state() { python3 "$(pwd)/scripts/vmw_state.py" "$@"; }

# Mark a module step complete.
vmw::step_done() { vmw::state done "$1" "$2"; }
# Check if a module step is complete (exit 0 if done).
vmw::step_done_p() { vmw::state has "module.$1.$2"; }

# =============================================================================
# DRY-RUN / PLAN MODE
# =============================================================================

VMW_DRY_RUN=0

vmw::dry_run_on()   { VMW_DRY_RUN=1; }
vmw::dry_run_off()  { VMW_DRY_RUN=0; }
vmw::dry_run_p()    { (( VMW_DRY_RUN == 1 )); }

# Runs a command (or prints it) depending on dry-run mode.
#   vmw::run <cmd...>
# Prints the command and returns 0 in dry-run mode; otherwise executes it.
vmw::run() {
    printf '  %b$ %b' "$TEXT_DIM" "$RESET"
    printf '%s ' "$@"
    printf '\n'
    if vmw::dry_run_p; then
        return 0
    fi
    "$@" &>>"$LOG_FILE"
}

# Steps through a list of command strings (one per argument), skipping ones
# already marked done in the state manifest. In dry-run mode prints all
# pending steps without executing them.
#   vmw::steps <module> "<cmd string>" "<cmd string>" ...
vmw::steps() {
    local module=$1; shift
    local cmd step
    for cmd in "$@"; do
        step="${cmd%% *}"
        if vmw::step_done_p "$module" "$step"; then
            fmtr::warn "[$module/$step] already done, skipping."
            continue
        fi
        printf '  %b$ %b%s\n' "$TEXT_DIM" "$RESET" "$cmd"
        if vmw::dry_run_p; then
            continue
        fi
        bash -c "$cmd" &>>"$LOG_FILE" || { fmtr::error "[$module/$step] failed."; return 1; }
        vmw::step_done "$module" "$step"
    done
    return 0
}

# =============================================================================
# AUTO-INIT (when sourced/executed)
# =============================================================================

log::init
compat::get_escalation_cmd
