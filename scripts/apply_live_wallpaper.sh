#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-live}" # "live" or "live_clock"
WALL_FILE="${2:-}"

if [[ -z "$WALL_FILE" ]]; then
    LAST_FILE="$HOME/.cache/wallpaper_picker/last_wallpaper"
    if [[ -f "$LAST_FILE" ]]; then
        WALL_FILE="$(cut -d'|' -f2- "$LAST_FILE")"
    fi
fi

if [[ -z "$WALL_FILE" || ! -f "$WALL_FILE" ]]; then
    echo "Error: Wallpaper file not found: $WALL_FILE" >&2
    exit 1
fi

SHOW_CLOCK="0"
if [[ "$MODE" == "live_clock" ]]; then
    SHOW_CLOCK="1"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Record live state
mkdir -p "$HOME/.cache/wallpaper_picker"
printf '%s|%s\n' "$MODE" "$WALL_FILE" > "$HOME/.cache/wallpaper_picker/live_mode"
printf 'image|%s\n' "$WALL_FILE" > "$HOME/.cache/wallpaper_picker/last_wallpaper"
cp -f "$WALL_FILE" /tmp/lock_bg.png 2>/dev/null || true

# Sync underlying static wallpaper and dynamic colors in the background
(
    if command -v awww >/dev/null 2>&1; then
        awww img "$WALL_FILE" --transition-type none >/dev/null 2>&1 || true
    fi
    if [[ -f "$SCRIPT_DIR/matugen_reload.sh" ]]; then
        HYPR_COLORS_PATH="${HYPR_COLORS_PATH:-$HOME/.config/hypr/modules/colors.lua}" \
            bash "$SCRIPT_DIR/matugen_reload.sh" "$WALL_FILE" >/dev/null 2>&1 || true
    fi
) >/dev/null 2>&1 &

# Terminate any previously running LiveWallpaper instance
quickshell kill -p "$PROJECT_DIR/LiveWallpaper.qml" >/dev/null 2>&1 || true
pkill -9 -f "qs-wallpaper-picker/LiveWallpaper.qml" >/dev/null 2>&1 || true
pkill -9 -f "hypr_cursor_stream.py" >/dev/null 2>&1 || true
sleep 0.08

INDEX_FILE="$HOME/.cache/wallpaper_picker/layers/index.json"
WALL_BASE="$(basename "$WALL_FILE")"
DEPTH_FILE=""
FG_FILE=""
BG_FILE=""

lookup_index() {
    [[ -f "$INDEX_FILE" ]] || return 0
    read -r DEPTH_FILE < <(python3 -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    print(d.get(sys.argv[3]) or d.get(sys.argv[2], ""))
except Exception:
    pass
' "$INDEX_FILE" "$WALL_BASE" "$WALL_FILE" 2>/dev/null || true)

    IFS=$'\t' read -r FG_FILE BG_FILE < <(python3 -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    fg = d.get(sys.argv[3] + ":fg") or d.get(sys.argv[2] + ":fg", "")
    bg = d.get(sys.argv[3] + ":bg") or d.get(sys.argv[2] + ":bg", "")
    print(f"{fg}\t{bg}" if (fg and bg) else "")
except Exception:
    pass
' "$INDEX_FILE" "$WALL_BASE" "$WALL_FILE" 2>/dev/null || true)
}

lookup_index

# Resolve discrete layers (fg/bg) first since generate_layers.py also ensures depth.png
if [[ -z "$FG_FILE" || ! -f "$FG_FILE" || -z "$BG_FILE" || ! -f "$BG_FILE" ]]; then
    uv run "$SCRIPT_DIR/generate_layers.py" "$WALL_FILE" >/dev/null 2>&1 || true
    lookup_index
fi

if [[ -z "$DEPTH_FILE" || ! -f "$DEPTH_FILE" ]]; then
    DEPTH_FILE="$(uv run "$SCRIPT_DIR/generate_depth.py" "$WALL_FILE" 2>/dev/null | tail -n 1 || true)"
fi

export LIVE_WALLPAPER_PATH="$WALL_FILE"
export LIVE_DEPTH_PATH="$DEPTH_FILE"
export LIVE_FG_PATH="$FG_FILE"
export LIVE_BG_PATH="$BG_FILE"
export LIVE_SHOW_CLOCK="$SHOW_CLOCK"

quickshell -d -p "$PROJECT_DIR/LiveWallpaper.qml" > /tmp/qs_live_wallpaper.log 2>&1
