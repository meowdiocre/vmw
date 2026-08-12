#!/usr/bin/env bash
# Runtime initialization with side effects:
#   - LOG_PATH / LOG_FILE setup
#   - ROOT_ESC (privilege escalation) detection
#
# Must be sourced AFTER lib/env.sh.
# No function definitions here — these run immediately on source.

# =============================================================================
# LOGGING (init)
# =============================================================================

log::init() {
    : "${LOG_PATH:=$VMW_ROOT/logs}"
    : "${LOG_FILE:=$LOG_PATH/$(date +%s).log}"

    export LOG_PATH LOG_FILE
    mkdir -p -- "$LOG_PATH" || { printf 'Failed to create log directory.\n' >&2; exit 1; }
    : >"$LOG_FILE"          || { printf 'Failed to create log file.\n' >&2; exit 1; }
}

# =============================================================================
# PRIVILEGE ESCALATION
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

log::init
compat::get_escalation_cmd
