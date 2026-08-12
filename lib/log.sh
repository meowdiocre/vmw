#!/usr/bin/env bash
# Logging + message formatting helpers.
#
# Requires: lib/env.sh (colors), lib/log_init.sh (LOG_FILE set up).
# All message helpers append to $LOG_FILE (set by log::init).

# =============================================================================
# LOW-LEVEL WRITE
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
