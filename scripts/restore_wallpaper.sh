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

LAST="$(wallpaper_cache_dir)/last_wallpaper"
DEFAULT_SOURCE="${QS_WALLPAPER_DIR:-$HOME/Wallpapers}"

[[ -f "$LAST" ]] || exit 0

wallpaper_type="$(cut -d'|' -f1 "$LAST")"
stored_path="$(cut -d'|' -f2- "$LAST")"

if [[ "$stored_path" = /* ]]; then
    wallpaper="$stored_path"
else
    wallpaper="$DEFAULT_SOURCE/$stored_path"
fi

if [[ ! -f "$wallpaper" ]]; then
    echo "Stored wallpaper no longer exists: $wallpaper" >&2
    exit 0
fi

pkill mpvpaper 2>/dev/null || true
if [[ ! -f "$(wallpaper_cache_dir)/live_mode" ]]; then
    quickshell kill -p "$PROJECT_DIR/LiveWallpaper.qml" 2>/dev/null || true
    pkill -9 -f "LiveWallpaper.qml" 2>/dev/null || true
    pkill -9 -f "hypr_cursor_stream.py" 2>/dev/null || true
else
    live_info="$(cat "$(wallpaper_cache_dir)/live_mode" 2>/dev/null || true)"
    live_mode_type="$(cut -d'|' -f1 <<< "$live_info")"
    live_wall_path="$(cut -d'|' -f2- <<< "$live_info")"
    if [[ -n "$live_wall_path" && -f "$live_wall_path" ]]; then
        bash "$SCRIPT_DIR/apply_live_wallpaper.sh" "$live_mode_type" "$live_wall_path" >/dev/null 2>&1 &
    fi
fi

if [[ "$wallpaper_type" == "video" ]]; then
    awww clear >/dev/null 2>&1 || true
    swww clear >/dev/null 2>&1 || true

    mpvpaper \
        -o 'loop --no-audio --hwdec=auto --profile=high-quality --video-sync=display-resample --interpolation --tscale=oversample --panscan=1.0 --video-unscaled=no' \
        '*' \
        "$wallpaper" \
        >/tmp/mpvpaper.log 2>&1 &
else
    awww img \
        --transition-type fade \
        --transition-duration 0.4 \
        "$wallpaper" \
        >/dev/null 2>&1 || true
fi

if [[ -f "$SCRIPT_DIR/pywal_sync.py" ]]; then
    python3 "$SCRIPT_DIR/pywal_sync.py" "$wallpaper" >/dev/null 2>&1 || true
    kill -USR1 $(pidof kitty 2>/dev/null) 2>/dev/null || true
    if command -v quickshell >/dev/null 2>&1 && pgrep -x quickshell >/dev/null 2>&1; then
        quickshell ipc call pywal reload >/dev/null 2>&1 || true
    fi
fi

ml4w_mode="${QS_WALLPAPER_ENABLE_ML4W:-0}"
ml4w_dir="$HOME/.cache/ml4w/hyprland-dotfiles"
ml4w_source="$wallpaper"

if [[ "$wallpaper_type" == "video" && -f /tmp/lock_bg.png ]]; then
    ml4w_source="/tmp/lock_bg.png"
fi

if [[ "$ml4w_mode" == "1" ]]; then
    mkdir -p "$ml4w_dir"

    printf '%s\n' "$wallpaper" \
        >"$ml4w_dir/current_wallpaper"

    if command -v magick >/dev/null 2>&1; then
        magick \
            "$ml4w_source" \
            -resize '2048x1280^' \
            -gravity center \
            -extent 2048x1280 \
            -blur 0x18 \
            "$ml4w_dir/blurred_wallpaper.png" \
            2>/dev/null || true
    fi

    printf '%s\n' \
        '* { current-image: url("'"$ml4w_dir"'/blurred_wallpaper.png", height); }' \
        >"$ml4w_dir/current_wallpaper.rasi"
fi
