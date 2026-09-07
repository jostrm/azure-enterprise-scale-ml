#!/usr/bin/env bash
# Shared terminal presentation. No shell options, traps, or command streams are changed.
# AIF_THEME=matrix|blue; AIF_COLOR=auto|always|never; NO_COLOR disables ANSI.

aif_color_enabled() {
    [[ -z "${NO_COLOR:-}" && "${AIF_COLOR:-auto}" != "never" ]] || return 1
    [[ "${AIF_COLOR:-auto}" == "always" ]] && return 0
    [[ "${TERM:-dumb}" != "dumb" && -t "${1:-1}" ]]
}

aif_palette() {
    AIF_RESET="" AIF_BOLD="" AIF_DIM="" AIF_ACCENT="" AIF_TEXT="" AIF_CYAN="" AIF_GREEN="" AIF_AMBER="" AIF_RED=""
    if aif_color_enabled "${1:-1}"; then
        AIF_RESET=$'\033[0m'
        AIF_BOLD=$'\033[1m'
        AIF_DIM=$'\033[2m'
        AIF_GREEN=$'\033[1;92m'
        AIF_CYAN=$'\033[1;96m'
        AIF_AMBER=$'\033[1;93m'
        AIF_RED=$'\033[1;91m'
        AIF_ACCENT="$AIF_GREEN"
        AIF_TEXT=$'\033[92m'
        if [[ "${AIF_THEME:-matrix}" == "blue" ]]; then
            AIF_ACCENT=$'\033[1;94m'
            AIF_TEXT=$'\033[96m'
        fi
    fi
    return 0
}

aif_rule() {
    local width="${COLUMNS:-72}" line
    [[ "$width" =~ ^[0-9]{1,3}$ ]] || width=72
    width=$((10#$width))
    (( width >= 24 )) || width=24
    (( width <= 88 )) || width=88
    printf -v line '%*s' "$((width - 4))" ''
    printf '  %s%s%s\n' "$AIF_DIM" "${line// /-}" "$AIF_RESET"
}

aif_banner() {
    aif_palette
    printf '\n  %s//%s %sA I   F A C T O R Y%s\n' "$AIF_CYAN" "$AIF_RESET" "$AIF_ACCENT" "$AIF_RESET"
    printf '  %sBOOTSTRAP CONSOLE%s  %s/ %s%s\n' "$AIF_ACCENT" "$AIF_RESET" "$AIF_CYAN" "$1" "$AIF_RESET"
    aif_rule
    [[ -z "${2:-}" ]] || printf '  %s%s%s\n' "$AIF_DIM" "$2" "$AIF_RESET"
    printf '\n'
}

aif_emit() {
    local level="$1" color text
    shift
    aif_palette
    case "$level" in
        OK) color="$AIF_GREEN" ;;
        WARN) color="$AIF_AMBER" ;;
        ERROR) color="$AIF_RED" ;;
        *) color="$AIF_CYAN" ;;
    esac
    text="$color"
    [[ "$level" != "INFO" ]] || text="$AIF_TEXT"
    printf '  %s[%s]%s %s%s%s\n' "$color" "$level" "$AIF_RESET" "$text" "$*" "$AIF_RESET"
}

aif_info() { aif_emit INFO "$@"; }
aif_success() { aif_emit OK "$@"; }
aif_warn() { aif_emit WARN "$@"; }
aif_error() { aif_emit ERROR "$@"; }

aif_section() {
    aif_palette
    printf '\n  %s>>%s %s%s%s\n' "$AIF_ACCENT" "$AIF_RESET" "$AIF_BOLD" "$*" "$AIF_RESET"
    aif_rule
}

aif_detail() {
    aif_palette
    printf '       %s%s%s\n' "$AIF_DIM" "$*" "$AIF_RESET"
}

aif_value() {
    aif_palette
    printf '  %s%-14s%s %s\n' "$AIF_CYAN" "$1" "$AIF_RESET" "$2"
}

aif_step() {
    aif_palette
    printf '  %s[%s]%s %s\n' "$AIF_ACCENT" "$1" "$AIF_RESET" "$2"
}

aif_stream() {
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        aif_detail "$line"
    done
}

aif_prompt() {
    # read -p writes to stderr, even though this string is captured via $(...).
    aif_palette 2
    printf '  %s?>%s %s' "$AIF_ACCENT" "$AIF_RESET" "$*"
}

aif_complete() {
    aif_palette
    aif_rule
    aif_success "$@"
    printf '\n'
}
