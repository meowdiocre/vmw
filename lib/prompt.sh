#!/usr/bin/env bash
# Interactive prompt helpers.
#
# Requires: lib/env.sh (colors), lib/log_init.sh (LOG_FILE).
# Portable to bash and zsh.

prmt::lower() {
    if [[ $BASH_VERSION ]]; then
        printf '%s' "${1,,}"
    else
        printf '%s' "${1:l}"
    fi
}

prmt::yes_or_no() {
    local prompt=$* ans
    while :; do
      printf '%s [y/n]: ' "$prompt"
      IFS= read -r ans
      printf '%s\n' "$ans" >>"$LOG_FILE"
      case "$(prmt::lower "${ans:-}")" in
        y*) return 0 ;;
        n*) return 1 ;;
        *)  printf '\n  [!] Please answer y/n\n' ;;
      esac
    done
}

prmt::quick_prompt() {
    local response
    printf '%s' "$1"
    IFS= read -r -n1 response
    printf '\n'
    printf '%s\n' "$response"
    printf '%s\n' "$response" >>"$LOG_FILE"
}
