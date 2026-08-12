#!/usr/bin/env bash
# Patch integrity helpers.
#
# Requires: lib/env.sh (VMW_ROOT), lib/log.sh, lib/run.sh (dry-run).

# Read a patch file's stamped target source version ('' if none).
vmw::patch_version() {
    PYTHONPATH="$VMW_ROOT/python" python3 -m vmw.patches version "$1"
}

# Verify all tracked patches against patches/checksums.sha256.
# In dry-run mode prints the check only. Returns 0 on success.
vmw::verify_patches() {
    if vmw::dry_run_p; then
        printf '  %b$ %b%s\n' "$TEXT_DIM" "$RESET" "python3 -m vmw.patches verify"
        return 0
    fi
    PYTHONPATH="$VMW_ROOT/python" python3 -m vmw.patches verify &>>"$LOG_FILE"
}

# Drift check: compare a patch's stamped version against the source being built.
#   vmw::check_patch_drift <patch_path> <expected_version> <source_label>
# Returns 0 if versions match or user confirms continue; 1 to abort.
vmw::check_patch_drift() {
    local patch_path=$1 expected=$2 label=$3
    local stamped
    stamped="$(vmw::patch_version "$patch_path")"
    if [[ -n "$stamped" && "$stamped" != "$expected" ]]; then
        fmtr::warn "Patch '$patch_path' targets $stamped but $label is $expected — drift detected."
        prmt::yes_or_no "$(fmtr::ask_inline "Continue anyway?")" || return 1
    fi
    return 0
}
