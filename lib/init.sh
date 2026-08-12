#!/usr/bin/env bash
# Unified bootstrap for all VMW scripts (bin/, modules/, scripts/).
#
# Source this first, in every script:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/init.sh"
#
# This resolves VMW_ROOT, then loads every lib module in dependency order.

# Resolve VMW_ROOT from this file's location (${BASH_SOURCE[0]:-$0} for zsh).
VMW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export VMW_ROOT

# shellcheck source=env.sh
. "$VMW_ROOT/lib/env.sh"
# shellcheck source=log.sh
. "$VMW_ROOT/lib/log.sh"
# shellcheck source=log_init.sh
. "$VMW_ROOT/lib/log_init.sh"     # side effects: LOG_FILE, ROOT_ESC
# shellcheck source=prompt.sh
. "$VMW_ROOT/lib/prompt.sh"
# shellcheck source=config.sh
. "$VMW_ROOT/lib/config.sh"
# shellcheck source=state.sh
. "$VMW_ROOT/lib/state.sh"
# shellcheck source=run.sh
. "$VMW_ROOT/lib/run.sh"
# shellcheck source=packages.sh
. "$VMW_ROOT/lib/packages.sh"
# shellcheck source=patches.sh
. "$VMW_ROOT/lib/patches.sh"
# shellcheck source=host.sh
. "$VMW_ROOT/lib/host.sh"

# Auto-detect the host (DISTRO + CPU) once, for every script.
vmw::detect_host
