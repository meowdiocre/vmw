#!/usr/bin/env bash
# Interactive prompt helpers.
#
# Requires: lib/env.sh (colors), lib/log_init.sh (LOG_FILE).

prmt::yes_or_no() {
    local prompt=$* ans
    while :; do
      read -rp "$prompt [y/n]: " ans
      printf '%s\n' "$ans" >>"$LOG_FILE"
      case ${ans,,} in
        y*) return 0 ;;
        n*) return 1 ;;
        *)  printf '\n  [!] Please answer y/n\n' ;;
      esac
    done
}

prmt::quick_prompt() {
    local response
    read -n1 -srp "$1" response
    printf '%s\n' "$response"
    printf '%s\n' "$response" >>"$LOG_FILE"
}
