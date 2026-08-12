#!/usr/bin/env bash
# Environment: ANSI escape codes, core vars, VMW_ROOT resolution.

# =============================================================================
# REPO ROOT
# =============================================================================
# VMW_ROOT resolves to the repository root regardless of the CWD the scripts
# are invoked from. All other lib files and modules depend on it.
# ${BASH_SOURCE[0]} is correct under bash; fall back to $0 for zsh sourcing.
VMW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

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
