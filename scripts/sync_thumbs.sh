#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &&
    pwd
)"
# shellcheck source=cache_paths.sh
source "$SCRIPT_DIR/cache_paths.sh"

SOURCE_DIR="${1:-${QS_WALLPAPER_DIR:-$HOME/Wallpapers}}"
THUMB_DIR="$(wallpaper_cache_dir)/thumbs"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Wallpaper directory does not exist: $SOURCE_DIR" >&2
    exit 2
fi

mkdir -p "$THUMB_DIR"

EXPECTED="$(mktemp)"
trap 'rm -f "$EXPECTED"' EXIT

find "$SOURCE_DIR" -maxdepth 1 -xtype f | while read -r f; do
    name="$(basename "$f")"
    ext="${name##*.}"
    ext="${ext,,}"
    case "$ext" in
        mp4|mkv|mov|webm) echo "000_${name}.jpg" ;;
        jpg|jpeg|png|webp|gif) echo "$name" ;;
    esac
done > "$EXPECTED"

process_file() {
    local source="$1"
    local name="$(basename "$source")"
    local extension="${name##*.}"
    extension="${extension,,}"
    local destination temporary

    case "$extension" in
        mp4|mkv|mov|webm)
            destination="$THUMB_DIR/000_${name}.jpg"
            if [[ -f "$destination" && "$destination" -nt "$source" ]]; then
                return 0
            fi
            if command -v ffmpeg >/dev/null 2>&1; then
                temporary="${destination}.tmp.jpg"
                if ffmpeg -y -ss 00:00:01 -i "$source" -frames:v 1 -vf 'scale=-2:720' "$temporary" >/dev/null 2>&1; then
                    mv -f "$temporary" "$destination"
                else
                    rm -f "$temporary"
                fi
            fi
            ;;
        jpg|jpeg|png|webp|gif)
            destination="$THUMB_DIR/$name"
            if [[ -f "$destination" && "$destination" -nt "$source" ]]; then
                return 0
            fi
            if command -v magick >/dev/null 2>&1; then
                temporary="${destination}.tmp.${extension}"
                if magick "${source}[0]" -auto-orient -thumbnail '1280x720>' "$temporary" 2>/dev/null; then
                    mv -f "$temporary" "$destination"
                else
                    rm -f "$temporary"
                fi
            fi
            ;;
    esac
}
export -f process_file
export THUMB_DIR

export MAGICK_THREAD_LIMIT=1
CORES="$(nproc 2>/dev/null || echo 4)"
find "$SOURCE_DIR" -maxdepth 1 -xtype f -print0 | xargs -0 -P "$CORES" -n 1 bash -c 'process_file "$@"' _

while IFS= read -r -d '' thumbnail; do
    name="$(basename "$thumbnail")"

    if ! grep -Fqx -- "$name" "$EXPECTED"; then
        rm -f "$thumbnail"
    fi
done < <(
    find "$THUMB_DIR" \
        -maxdepth 1 \
        -type f \
        -print0
)
