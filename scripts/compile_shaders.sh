#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SHADERS_DIR="$PROJECT_DIR/shaders"

QSB_BIN="/usr/lib/qt6/bin/qsb"
if ! command -v "$QSB_BIN" >/dev/null 2>&1; then
    QSB_BIN="$(command -v qsb || true)"
fi

if [[ -z "$QSB_BIN" ]]; then
    echo "Error: Qt Shader Baker (qsb) not found in /usr/lib/qt6/bin/qsb or PATH" >&2
    exit 1
fi

echo "Compiling shaders with $QSB_BIN..."
"$QSB_BIN" --glsl "100 es,120,150,440" --hlsl 50 --msl 12 \
    -o "$SHADERS_DIR/depth_parallax.vert.qsb" \
    "$SHADERS_DIR/depth_parallax.vert"

"$QSB_BIN" --glsl "100 es,120,150,440" --hlsl 50 --msl 12 \
    -o "$SHADERS_DIR/depth_parallax.frag.qsb" \
    "$SHADERS_DIR/depth_parallax.frag"

echo "Successfully generated: $SHADERS_DIR/depth_parallax.{vert,frag}.qsb"
