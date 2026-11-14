#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &&
    pwd
)"
PROJECT_DIR="$(
    cd -- "$SCRIPT_DIR/.." &&
    pwd
)"

# shellcheck source=cache_paths.sh
source "$SCRIPT_DIR/cache_paths.sh"

WALLPAPER_DIR="${QS_WALLPAPER_DIR:-$HOME/Wallpapers}"
STATE_DIR="$(wallpaper_cache_dir)"

ensure_wallpaper_cache_compatibility
mkdir -p "$WALLPAPER_DIR" "$STATE_DIR"

# Toggle: if the wallpaper picker is already open, close it instantly
if quickshell kill -p "$PROJECT_DIR/Main.qml" 2>/dev/null || pkill -f "qs-wallpaper-picker/Main.qml" 2>/dev/null; then
    exit 0
fi

# Ensure awww-daemon is running and conflicting daemons are stopped
if ! pgrep -x awww-daemon >/dev/null 2>&1; then
    awww-daemon &
fi
pkill hyprpaper 2>/dev/null || true

# Background sync if wallpapers or Pictures directory changed
SYNC_STAMP="$STATE_DIR/.last_sync"
sync_needed=0

if [[ ! -f "$SYNC_STAMP" ]]; then
    sync_needed=1
elif [[ -d "$HOME/Pictures/Wallpapers" && "$HOME/Pictures/Wallpapers" -nt "$SYNC_STAMP" ]]; then
    sync_needed=1
elif [[ "$WALLPAPER_DIR" -nt "$SYNC_STAMP" ]]; then
    sync_needed=1
fi

if [[ "$sync_needed" -eq 1 ]]; then
    (
        if [[ -d "$HOME/Pictures/Wallpapers" && "$WALLPAPER_DIR" == "$HOME/Wallpapers" ]]; then
            find "$HOME/Pictures/Wallpapers" -mindepth 2 -type f \( -iname "*.jpg" -o -iname "*.png" -o -iname "*.jpeg" -o -iname "*.webp" -o -iname "*.mp4" -o -iname "*.webm" -o -iname "*.mkv" -o -iname "*.mov" \) 2>/dev/null | while read -r img; do
                rel="${img#$HOME/Pictures/Wallpapers/}"
                flat_name="${rel//\//_}"
                target="$WALLPAPER_DIR/$flat_name"
                [[ -e "$target" ]] || ln -s "$img" "$target"
            done
        fi

        "$SCRIPT_DIR/sync_thumbs.sh" "$WALLPAPER_DIR" >/dev/null 2>&1 || true
        touch "$SYNC_STAMP"
    ) & disown
fi

export QS_WALLPAPER_ENABLE_ML4W="${QS_WALLPAPER_ENABLE_ML4W:-0}"

LAST_WALL=""
if [[ -f "$STATE_DIR/live_mode" && ( ! -f "$STATE_DIR/last_wallpaper" || "$STATE_DIR/live_mode" -nt "$STATE_DIR/last_wallpaper" ) ]]; then
    LAST_PATH="$(cut -d'|' -f2- "$STATE_DIR/live_mode" 2>/dev/null || true)"
    if [[ -n "$LAST_PATH" ]]; then
        LAST_WALL="$(basename "$LAST_PATH")"
    fi
elif [[ -f "$STATE_DIR/last_wallpaper" ]]; then
    LAST_PATH="$(cut -d'|' -f2- "$STATE_DIR/last_wallpaper" 2>/dev/null || true)"
    if [[ -n "$LAST_PATH" ]]; then
        LAST_WALL="$(basename "$LAST_PATH")"
    fi
fi
export QS_CURRENT_WALLPAPER="$LAST_WALL"

if command -v flock >/dev/null 2>&1; then
    exec flock -n -o \
        "$STATE_DIR/picker.lock" \
        quickshell -p "$PROJECT_DIR/Main.qml"
fi

exec quickshell -p "$PROJECT_DIR/Main.qml"
