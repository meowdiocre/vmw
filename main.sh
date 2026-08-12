#!/usr/bin/env bash
# VMW - VM Workspace (backward-compatible entrypoint).
#
# Thin wrapper around bin/vmw so `./main.sh` keeps working. All logic
# lives in bin/vmw and lib/.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/bin/vmw" "$@"
