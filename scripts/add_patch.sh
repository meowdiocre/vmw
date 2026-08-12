#!/usr/bin/env bash
# Stamp target-source version metadata into a patch header and refresh
# patches/checksums.sha256.
#
# Usage: scripts/add_patch.sh <patch-path> [<target-version>]
#   target-version is read from an existing '# Source:' line if not given.
#
# Example:
#   scripts/add_patch.sh patches/QEMU/AMD-v11.0.4.patch v11.0.4

set -euo pipefail

VMW_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

patch_path="${1:?usage: add_patch.sh <patch-path> [<target-version>]}"
version="${2:-}"

[[ -f "$patch_path" ]] || { echo "error: no such patch: $patch_path" >&2; exit 1; }

# Normalize path relative to repo root
patch_path="$(realpath --relative-to="$VMW_ROOT" "$patch_path")"

# Infer version from filename if not given
if [[ -z $version ]]; then
    base="$(basename "$patch_path")"
    case "$base" in
        *-v[0-9]*.patch) version="$(grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' <<<"$base" | head -1)" ;;
        *-stable*.patch) version="$(grep -oE 'edk2-stable[0-9]+' <<<"$base" | head -1)" ;;
        *) version="" ;;
    esac
fi

tmp="$(mktemp)"
{
    echo "# Source: ${version:-unknown}"
    echo "# Applied by: VMW"
    echo "# (checksum tracked in patches/checksums.sha256)"
    echo ""
    cat "$patch_path"
} > "$tmp"

# Only add header if not already present
if ! grep -q '^# Source:' "$patch_path"; then
    mv "$tmp" "$patch_path"
    echo "Stamped '# Source: ${version:-unknown}' into $patch_path"
else
    rm -f "$tmp"
    echo "Patch already has a '# Source:' header: $(grep -m1 '^# Source:' "$patch_path")"
fi

PYTHONPATH="$VMW_ROOT/python" python3 -m vmw.patches gen
echo "Updated checksums."
