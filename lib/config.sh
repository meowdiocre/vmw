#!/usr/bin/env bash
# Declarative YAML profile loading.
#
# Requires: lib/env.sh (VMW_ROOT), lib/log.sh (fmtr::*).
# Conventions:
#   profiles live in $VMW_ROOT/configs/<name>.yml
#   flattened keys become CFG_<UPPER_SNAKE_CASE> shell vars

vmw::py() { PYTHONPATH="$VMW_ROOT/python" python3 -m vmw "$@"; }

# Loads a configs/<profile>.yml profile into CFG_* variables.
#   vmw::load_config <profile>   # e.g. vmud (no .yml suffix)
# Returns 0 on success, 1 if the profile doesn't exist.
vmw::load_config() {
    local profile=$1
    [[ -n $profile ]] || profile="vmud"
    CONFIG_PROFILE="$profile"
    CONFIG_FILE="$VMW_ROOT/configs/${profile}.yml"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        fmtr::error "Config profile '$profile' not found at $CONFIG_FILE"
        return 1
    fi

    local cfg_script
    cfg_script="$(PYTHONPATH="$VMW_ROOT/python" python3 -m vmw.yaml "$CONFIG_FILE")" || {
        fmtr::error "Failed to parse YAML profile '$profile'."
        return 1
    }

    # Clear any previously loaded CFG_* values (portable to bash + zsh).
    if [[ $BASH_VERSION ]]; then
        unset "${!CFG_@}" 2>/dev/null || true
    else
        unset ${(k)parameters[(I)CFG_*]} 2>/dev/null || true
    fi

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
        key="${key^^}"
        printf '%s' "${!key-}"
    else
        # zsh indirect expansion
        key="${(U)key}"
        printf '%s' "${(P)key:-}"
    fi
}

# Returns 0 (true) if the given config path is set and non-empty.
vmw::has_cfg() {
    local val
    val="$(vmw::cfg "$1")"
    [[ -n $val ]]
}
