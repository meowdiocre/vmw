#!/usr/bin/env bash

. "$(dirname "${BASH_SOURCE[0]}")/../lib/init.sh"

# =============================================================================
# VMW deploy: generate libvirt domain XML from a YAML profile and define it.
#
#   deploy.sh <profile>          # e.g. deploy.sh vmud
#   deploy.sh --dry-run <profile># print the XML without defining
#   deploy.sh --print <profile>  # write XML to configs/<profile>.xml (gitignored)
#
# Replaces the old interactive virt-install flow with a deterministic,
# schema-validated generator (python/vmw/genxml.py).
#
# Note: the generator does not yet emit -acpitable args, machine args,
# or hostdev passthrough entries. See RESEARCH.md section 9.
# =============================================================================

PROFILE="${1:-}"
DRY=""
PRINT=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --print)   PRINT=1 ;;
        -h|--help)
            echo "Usage: deploy.sh [--dry-run|--print] <profile>"
            echo "  <profile>   name of a configs/<profile>.yml"
            echo "  --dry-run   print generated XML without defining the domain"
            echo "  --print     write XML to configs/<profile>.xml"
            exit 0
            ;;
        *) PROFILE="$arg" ;;
    esac
done

if [[ -z $PROFILE ]]; then
    fmtr::error "No profile specified. Usage: deploy.sh <profile>"
    exit 1
fi

# Load profile into CFG_* vars
if ! vmw::load_config "$PROFILE"; then
    exit 1
fi

OUT_XML="$VMW_ROOT/configs/${PROFILE}.xml"

fmtr::info "Generating domain XML for profile '$PROFILE'..."

if [[ -n $PRINT ]]; then
    vmw::py genxml "$PROFILE" --output "$OUT_XML" || exit 1
    fmtr::info "Wrote XML to $OUT_XML"
    exit 0
fi

if [[ -n $DRY ]]; then
    vmw::py genxml "$PROFILE" || exit 1
    exit 0
fi

# Generate to the output file (in configs/, gitignored)
vmw::py genxml "$PROFILE" --output "$OUT_XML" || exit 1

# Schema validation via virt-xml-validate (if present)
if command -v virt-xml-validate >/dev/null 2>&1; then
    fmtr::info "Validating against libvirt schema..."
    if ! virt-xml-validate "$OUT_XML" domain &>>"$LOG_FILE"; then
        fmtr::error "Generated XML failed schema validation."
        tail -20 "$LOG_FILE"
        exit 1
    fi
    fmtr::log "Schema validation passed."
fi

DOMAIN_NAME="${CFG_NAME:-$PROFILE}"

# Refuse to clobber an existing domain
if $ROOT_ESC virsh dominfo "$DOMAIN_NAME" >/dev/null 2>&1; then
    fmtr::error "Domain '$DOMAIN_NAME' already exists. Undefine it first:"
    fmtr::error "  $ROOT_ESC virsh undefine --nvram '$DOMAIN_NAME'"
    exit 1
fi

fmtr::info "Defining domain '$DOMAIN_NAME'..."
if ! $ROOT_ESC virsh define "$OUT_XML" &>>"$LOG_FILE"; then
    fmtr::error "virsh define failed. See $LOG_FILE"
    exit 1
fi

fmtr::log "Domain '$DOMAIN_NAME' defined from $OUT_XML"
fmtr::info "Start it with: $ROOT_ESC virsh start '$DOMAIN_NAME'"
