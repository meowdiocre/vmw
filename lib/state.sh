#!/usr/bin/env bash
# Idempotency state manifest (.vmw/state.json).
#
# Requires: lib/env.sh (VMW_ROOT). Backed by python/vmw/state.py.

vmw::state() { PYTHONPATH="$VMW_ROOT/python" python3 -m vmw.state "$@"; }

# Mark a module step complete.
vmw::step_done() { vmw::state done "$1" "$2"; }
# vmw::step_done_p is defined in lib/probe.sh (manifest + real-system check).
