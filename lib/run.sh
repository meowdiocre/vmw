#!/usr/bin/env bash
# Command execution: dry-run / plan mode + step runner.
#
# Requires: lib/env.sh (colors, VMW_ROOT), lib/log.sh, lib/log_init.sh,
#           lib/state.sh.

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
