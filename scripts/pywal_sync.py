#!/usr/bin/env python3
"""
pywal_sync.py - Dynamic Pywal color generation and caching for Quickshell & Hyprland
- Checks cache per wallpaper before generating colors to save compute.
- Bar colors: derived from the top half of the wallpaper.
- Dock colors: derived from the bottom half of the wallpaper.
- Hyprland window border: top-to-bottom gradient (180deg) using whole/top-to-bottom palette.
- Palettes are guaranteed dark-theme with proper contrast and readability.
- Pywal never touches or hijacks terminal colors.
"""

import colorsys
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import re
import sys
from pathlib import Path
from PIL import Image
import pywal

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}


def hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    return tuple(int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(r: float, g: float, b: float) -> str:
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def atomic_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst_tmp = dst.parent / f"{dst.name}.tmp.{os.getpid()}"
    shutil.copyfile(src, dst_tmp)
    os.replace(dst_tmp, dst)


def hex_to_hls(hex_str: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(hex_str)
    return colorsys.rgb_to_hls(r, g, b)


def hls_to_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return rgb_to_hex(r, g, b)


def enhance_dark_palette(raw_dict: dict, img_path: Path | None = None) -> dict:
    """
    Ensure the palette produces a clean, accessible dark theme:
    - Background: dark surface base (lightness 0.075-0.095), subtle tint.
    - Foreground: high-contrast text (lightness ~0.92, AAA contrast > 10:1).
    - Color 8: defined muted outline/border (lightness ~0.48).
    - Color 4: vibrant, readable primary accent tuned from image dominant hue.
    - Colors 1-3: clear semantic status colors (red/error, green/success, amber/warning).
    - Colors 5-6: harmonious secondary/tertiary accents.
    - Colors 9-14: bright counterparts.
    """
    raw_special = raw_dict.get("special", {})
    raw_colors = raw_dict.get("colors", {})

    raw_bg = raw_special.get("background") or raw_colors.get("color0") or "#0f1214"
    h_bg, l_bg, s_bg = hex_to_hls(raw_bg)

    color_candidates = []
    for k in ["color4", "color1", "color2", "color3", "color5", "color6"]:
        c_hex = raw_colors.get(k)
        if c_hex:
            ch, cl, cs = hex_to_hls(c_hex)
            color_candidates.append((k, ch, cl, cs))

    img_vibrant_h = None
    img_vibrant_s = 0.0
    if img_path and img_path.is_file():
        try:
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                sample = im.resize((48, 48), Image.Resampling.BOX)
                if hasattr(sample, "get_flattened_data"):
                    flat = list(sample.get_flattened_data())
                    pixels = [(flat[i], flat[i+1], flat[i+2]) for i in range(0, len(flat), 3)]
                else:
                    pixels = list(sample.getdata())
                v_list = []
                for p in pixels:
                    rn, gn, bn = p[0] / 255.0, p[1] / 255.0, p[2] / 255.0
                    ph, pl, ps = colorsys.rgb_to_hls(rn, gn, bn)
                    if ps > 0.15 and 0.20 < pl < 0.85:
                        v_list.append((ph, pl, ps))
                if v_list:
                    v_list.sort(key=lambda x: x[2] * (1.0 - abs(x[1] - 0.55)), reverse=True)
                    img_vibrant_h = v_list[0][0]
                    img_vibrant_s = v_list[0][2]
        except Exception:
            pass

    raw_c4 = raw_colors.get("color4") or "#33ccff"
    h_c4, l_c4, s_c4 = hex_to_hls(raw_c4)

    chosen_h = h_c4
    chosen_s = s_c4
    if s_c4 < 0.10:
        best_candidate = max(color_candidates, key=lambda x: x[3], default=None)
        if best_candidate and best_candidate[3] > 0.15:
            chosen_h = best_candidate[1]
            chosen_s = best_candidate[3]
        elif img_vibrant_h is not None and img_vibrant_s > 0.15:
            chosen_h = img_vibrant_h
            chosen_s = img_vibrant_s

    # 1. Background & Base Color0
    bg_l = 0.085
    if s_bg < 0.05 and chosen_s >= 0.10:
        h_bg = chosen_h
        bg_s = 0.12
    else:
        bg_s = min(max(s_bg, 0.08), 0.18)

    dark_bg = hls_to_hex(h_bg, bg_l, bg_s)
    dark_c0 = hls_to_hex(h_bg, 0.065, bg_s)

    # 2. Foreground & Cursor
    fg_l = 0.92
    fg_s = min(bg_s, 0.04)
    light_fg = hls_to_hex(h_bg, fg_l, fg_s)

    # 3. Muted text & outlines (color8)
    c8_l = 0.48
    c8_s = min(max(bg_s, 0.12), 0.22)
    color8 = hls_to_hex(h_bg, c8_l, c8_s)

    # 4. Secondary foreground (color7) & Pure bright foreground (color15)
    color7 = hls_to_hex(h_bg, 0.80, fg_s)
    color15 = hls_to_hex(h_bg, 0.96, 0.02)

    # 5. Primary Accent (color4)
    if chosen_s < 0.08:
        c4_h = 217.0 / 360.0
        c4_s = 0.70
    else:
        c4_h = chosen_h
        c4_s = max(0.60, min(0.85, chosen_s * 2.8))
    color4 = hls_to_hex(c4_h, 0.65, c4_s)

    # 6. Secondary (color5) & Tertiary (color6) Accents
    raw_c5 = raw_colors.get("color5") or "#9a847d"
    h_c5, l_c5, s_c5 = hex_to_hls(raw_c5)
    hue_dist5 = abs(h_c5 - c4_h)
    hue_dist5 = min(hue_dist5, 1.0 - hue_dist5)
    if hue_dist5 > 0.07 and s_c5 > 0.10:
        c5_s = max(0.55, min(0.80, s_c5 * 2.5))
        color5 = hls_to_hex(h_c5, 0.65, c5_s)
    else:
        color5 = hls_to_hex((c4_h + 0.12) % 1.0, 0.65, 0.65)

    raw_c6 = raw_colors.get("color6") or "#708991"
    h_c6, l_c6, s_c6 = hex_to_hls(raw_c6)
    hue_dist6 = abs(h_c6 - c4_h)
    hue_dist6 = min(hue_dist6, 1.0 - hue_dist6)
    h_c5_final, _, _ = hex_to_hls(color5)
    dist_5_6 = abs(h_c6 - h_c5_final)
    dist_5_6 = min(dist_5_6, 1.0 - dist_5_6)
    if hue_dist6 > 0.07 and s_c6 > 0.10 and dist_5_6 > 0.07:
        c6_s = max(0.55, min(0.80, s_c6 * 2.5))
        color6 = hls_to_hex(h_c6, 0.65, c6_s)
    else:
        color6 = hls_to_hex((c4_h + 0.45) % 1.0, 0.65, 0.65)

    # 7. Semantic status colors
    color1 = hls_to_hex(4.0 / 360.0, 0.65, 0.78)    # Red / Error
    color2 = hls_to_hex(142.0 / 360.0, 0.64, 0.65)  # Green / Success
    color3 = hls_to_hex(40.0 / 360.0, 0.68, 0.85)   # Amber / Warning

    # 8. Bright variants (color9 - color14)
    color9 = hls_to_hex(4.0 / 360.0, 0.72, 0.82)
    color10 = hls_to_hex(142.0 / 360.0, 0.71, 0.70)
    color11 = hls_to_hex(40.0 / 360.0, 0.75, 0.88)
    color12 = hls_to_hex(c4_h, 0.72, c4_s)
    color13 = hls_to_hex(hex_to_hls(color5)[0], 0.72, 0.70)
    color14 = hls_to_hex(hex_to_hls(color6)[0], 0.72, 0.70)

    return {
        "wallpaper": raw_dict.get("wallpaper", ""),
        "alpha": "100",
        "special": {
            "background": dark_bg,
            "foreground": light_fg,
            "cursor": light_fg
        },
        "colors": {
            "color0": dark_c0,
            "color1": color1,
            "color2": color2,
            "color3": color3,
            "color4": color4,
            "color5": color5,
            "color6": color6,
            "color7": color7,
            "color8": color8,
            "color9": color9,
            "color10": color10,
            "color11": color11,
            "color12": color12,
            "color13": color13,
            "color14": color14,
            "color15": color15
        }
    }


def safe_extract_colors(img_path: Path) -> dict:
    try:
        return pywal.colors.get(str(img_path), backend="wal")
    except (SystemExit, Exception):
        try:
            out = subprocess.check_output(
                ["magick", f"{img_path}[0]", "-resize", "25%", "-colors", "16", "-unique-colors", "txt:-"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8", errors="ignore")
            hex_cols = re.findall(r"#(?:[0-9a-fA-F]{6})", out)
        except Exception:
            hex_cols = []

        if not hex_cols:
            hex_cols = ["#1e1e2e", "#89b4fa", "#f38ba8", "#a6e3a1", "#f9e2af", "#cdd6f4", "#b4befe", "#fab387"]

        while len(hex_cols) < 16:
            hex_cols.extend(hex_cols)
        hex_cols = hex_cols[:16]
        return pywal.colors.colors_to_dict(hex_cols, str(img_path))


def resolve_image_path(input_path: str) -> Path | None:
    p = Path(input_path).expanduser().resolve()
    if not p.exists():
        home = Path.home()
        alt = home / "Wallpapers" / input_path
        if alt.exists():
            p = alt.resolve()
        else:
            return None

    if p.suffix.lower() in VIDEO_EXTENSIONS:
        thumb_dir = _xdg_cache_dir() / "wallpaper_picker" / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)

        candidates = [
            thumb_dir / f"000_{p.name}.jpg",
            thumb_dir / f"{p.name}.jpg",
            thumb_dir / f"{p.stem}.jpg"
        ]
        for c in candidates:
            if c.is_file():
                return c

        gen_thumb = thumb_dir / f"000_{p.name}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", "00:00:01", "-i", str(p),
                "-frames:v", "1", "-vf", "scale=-2:720", str(gen_thumb)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if gen_thumb.is_file():
                return gen_thumb
        except Exception as e:
            sys.stderr.write(f"Failed to generate video thumbnail: {e}\n")
            return None

    return p if p.is_file() else None


def compute_cache_key(image_path: Path) -> str:
    stat = image_path.stat()
    key_str = f"v3:{image_path}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:24]


def get_wal_dir() -> Path:
    if "WAL_DIR" in os.environ:
        p = Path(os.environ["WAL_DIR"]).expanduser().resolve()
    else:
        p = Path.home() / ".cache" / "wal"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _xdg_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    return Path(xdg).expanduser() if xdg else (Path.home() / ".cache")


def atomic_write_text(dest_path: Path, content: str, encoding: str = "utf-8") -> None:
    import tempfile

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest_path.parent), prefix=f".{dest_path.name}.")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_name, 0o644)
        except OSError:
            pass
        os.replace(tmp_name, dest_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_cache_base_dir() -> Path:
    if "WAL_CACHE_BASE_DIR" in os.environ:
        p = Path(os.environ["WAL_CACHE_BASE_DIR"]).expanduser().resolve()
    else:
        p = _xdg_cache_dir() / "wallpaper_picker" / "pywal_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_hypr_colors_path() -> Path:
    if "HYPR_COLORS_PATH" in os.environ:
        return Path(os.environ["HYPR_COLORS_PATH"]).expanduser().resolve()
    return Path.home() / ".config" / "hypr" / "modules" / "colors.lua"


def apply_hyprland_border(top_hex: str, bot_hex: str, inact_hex: str, angle: int = 180):
    hypr_colors_path = get_hypr_colors_path()
    hypr_colors_path.parent.mkdir(parents=True, exist_ok=True)

    lua_content = f"""-- ============================================================================
-- DYNAMIC WALLPAPER COLORS (WINDOW BORDERS)
-- Autogenerated by wallpaper picker pywal sync
-- ============================================================================
hl.config({{
\tgeneral = {{
\t\t["col.active_border"] = {{
\t\t\tcolors = {{ "rgba({top_hex}ee)", "rgba({bot_hex}ee)" }},
\t\t\tangle = {angle},
\t\t}},
\t\t["col.inactive_border"] = "rgba({inact_hex}aa)",
\t}},
}})
"""
    try:
        atomic_write_text(hypr_colors_path, lua_content)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write {hypr_colors_path}: {e}\n")

    if os.environ.get("PYWAL_NO_HYPRCTL") == "1":
        return

    # Dynamically update running Hyprland instance
    eval_cmd = (
        f'hl.config({{ general = {{ '
        f'["col.active_border"] = {{ colors = {{ "rgba({top_hex}ee)", "rgba({bot_hex}ee)" }}, angle = {angle} }}, '
        f'["col.inactive_border"] = "rgba({inact_hex}aa)" }} }})'
    )
    try:
        subprocess.run(["hyprctl", "eval", eval_cmd], capture_output=True, timeout=2)
    except Exception:
        pass


def notify_quickshell():
    if os.environ.get("PYWAL_NO_QUICKSHELL") == "1" or os.environ.get("PYWAL_NO_HYPRCTL") == "1":
        return
    try:
        subprocess.run(["quickshell", "ipc", "call", "pywal", "reload"], capture_output=True, timeout=2)
    except Exception:
        pass


def _hex_to_rgb255(hex_str: str) -> str:
    r, g, b = hex_to_rgb(hex_str)
    return f"{int(round(r * 255))},{int(round(g * 255))},{int(round(b * 255))}"


def _mix_hex(hex_a: str, hex_b: str, t: float) -> str:
    ra, ga, ba = hex_to_rgb(hex_a)
    rb, gb, bb = hex_to_rgb(hex_b)
    return rgb_to_hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def _contrast_fg(bg_hex: str, light_fg: str, dark_fg: str) -> str:
    r, g, b = hex_to_rgb(bg_hex)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return dark_fg if lum > 0.45 else light_fg


def apply_kde_colors(palette: dict):
    """Sync dynamic pywal palette into kdeglobals & PywalDynamic.colors for unified Qt/Dolphin visuals."""
    if os.environ.get("PYWAL_NO_KDE") == "1":
        return
    if os.environ.get("PYWAL_NO_HYPRCTL") == "1" and "KDEGLOBALS_PATH" not in os.environ:
        return

    special = palette.get("special", {})
    colors = palette.get("colors", {})
    bg = special.get("background") or colors.get("color0") or "#12121a"
    fg = special.get("foreground") or colors.get("color15") or "#eaeaeb"
    accent = colors.get("color4") or "#885af2"
    accent_alt = colors.get("color5") or accent
    fg_muted = _mix_hex(bg, fg, 0.58)
    bg_alt = _mix_hex(bg, fg, 0.035)
    bg_surface = _mix_hex(bg, fg, 0.075)
    accent_dim = _mix_hex(bg, accent, 0.35)
    sel_fg = _contrast_fg(accent, fg, colors.get("color0") or "#0e0e14")

    c_bg = _hex_to_rgb255(bg)
    c_bg_alt = _hex_to_rgb255(bg_alt)
    c_bg_surf = _hex_to_rgb255(bg_surface)
    c_fg = _hex_to_rgb255(fg)
    c_fg_muted = _hex_to_rgb255(fg_muted)
    c_acc = _hex_to_rgb255(accent)
    c_acc_dim = _hex_to_rgb255(accent_dim)
    c_sel_fg = _hex_to_rgb255(sel_fg)
    c_link = _hex_to_rgb255(accent_alt)
    c_neg = _hex_to_rgb255(colors.get("color1") or "#eb6960")
    c_pos = _hex_to_rgb255(colors.get("color2") or "#68df93")
    c_neu = _hex_to_rgb255(colors.get("color3") or "#f3c568")
    c_vis = c_acc

    def make_group(bg_norm: str, bg_alt_v: str, fg_norm: str = c_fg) -> dict[str, str]:
        return {
            "BackgroundAlternate": bg_alt_v,
            "BackgroundNormal": bg_norm,
            "DecorationFocus": c_acc,
            "DecorationHover": c_acc,
            "ForegroundActive": c_acc,
            "ForegroundInactive": c_fg_muted,
            "ForegroundLink": c_link,
            "ForegroundNegative": c_neg,
            "ForegroundNeutral": c_neu,
            "ForegroundNormal": fg_norm,
            "ForegroundPositive": c_pos,
            "ForegroundVisited": c_vis,
        }

    # Unify Window, View, Header, Complementary backgrounds so Dolphin panels form one seamless surface
    sections: dict[str, dict[str, str]] = {
        "Colors:Window": make_group(c_bg, c_bg_alt),
        "Colors:View": make_group(c_bg, c_bg_alt),
        "Colors:Header": make_group(c_bg, c_bg_alt),
        "Colors:Header][Inactive": make_group(c_bg, c_bg_alt),
        "Colors:Complementary": make_group(c_bg, c_bg_alt),
        "Colors:Button": make_group(c_bg_surf, c_acc_dim),
        "Colors:Tooltip": make_group(c_bg_surf, c_bg_alt),
        "Colors:Selection": make_group(c_acc, c_acc_dim, c_sel_fg),
        "WM": {
            "activeBackground": c_bg,
            "activeBlend": c_fg,
            "activeForeground": c_fg,
            "inactiveBackground": c_bg,
            "inactiveBlend": c_fg_muted,
            "inactiveForeground": c_fg_muted,
        },
    }

    kdeglobals_path = Path(os.environ.get("KDEGLOBALS_PATH", str(Path.home() / ".config" / "kdeglobals")))
    kdeglobals_path.parent.mkdir(parents=True, exist_ok=True)

    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    if kdeglobals_path.is_file():
        try:
            cp.read(kdeglobals_path, encoding="utf-8")
        except Exception:
            pass

    for sec, vals in sections.items():
        if not cp.has_section(sec):
            cp.add_section(sec)
        for k, v in vals.items():
            cp.set(sec, k, v)

    if not cp.has_section("General"):
        cp.add_section("General")
    cp.set("General", "ColorScheme", "PywalDynamic")
    cp.set("General", "AccentColor", c_acc)
    cp.set("General", "LastUsedCustomAccentColor", c_acc)

    tmp_kde = kdeglobals_path.parent / f"{kdeglobals_path.name}.tmp.{os.getpid()}"
    with tmp_kde.open("w", encoding="utf-8") as f:
        cp.write(f, space_around_delimiters=False)
    os.replace(tmp_kde, kdeglobals_path)

    # Also write color-scheme file when updating real user config
    if "KDEGLOBALS_PATH" not in os.environ:
        scheme_path = Path.home() / ".local" / "share" / "color-schemes" / "PywalDynamic.colors"
        scheme_path.parent.mkdir(parents=True, exist_ok=True)
        scp = configparser.ConfigParser(interpolation=None)
        scp.optionxform = str
        for sec, vals in sections.items():
            scp.add_section(sec)
            for k, v in vals.items():
                scp.set(sec, k, v)
        scp.add_section("General")
        scp.set("General", "ColorScheme", "PywalDynamic")
        scp.set("General", "Name", "PywalDynamic")
        scp.set("General", "shadeSortColumn", "true")
        tmp_scheme = scheme_path.parent / f"{scheme_path.name}.tmp.{os.getpid()}"
        with tmp_scheme.open("w", encoding="utf-8") as f:
            scp.write(f, space_around_delimiters=False)
        os.replace(tmp_scheme, scheme_path)

        if os.environ.get("PYWAL_NO_HYPRCTL") != "1":
            try:
                subprocess.run(
                    [
                        "dbus-send", "--session", "--type=signal",
                        "/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange",
                        "int32:0", "int32:0",
                    ],
                    capture_output=True,
                    timeout=2,
                )
            except Exception:
                pass


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        sys.exit(0)

    raw_path = sys.argv[1]
    image_path = resolve_image_path(raw_path)
    if not image_path:
        sys.stderr.write(f"Error: Could not resolve valid image for: {raw_path}\n")
        sys.exit(1)

    cache_key = compute_cache_key(image_path)
    cache_base = get_cache_base_dir() / cache_key
    wal_dir = get_wal_dir()

    cache_full = cache_base / "colors.json"
    cache_bar = cache_base / "colors-bar.json"
    cache_dock = cache_base / "colors-dock.json"
    cache_meta = cache_base / "meta.json"

    # --- 1. CHECK CACHE (Save Compute) ---
    if cache_full.is_file() and cache_bar.is_file() and cache_dock.is_file() and cache_meta.is_file():
        # Instant cache hit
        atomic_copy(cache_full, wal_dir / "colors.json")
        atomic_copy(cache_bar, wal_dir / "colors-bar.json")
        atomic_copy(cache_dock, wal_dir / "colors-dock.json")

        try:
            meta = json.loads(cache_meta.read_text())
            apply_hyprland_border(
                meta.get("top_color", "33ccff"),
                meta.get("bot_color", "00ff99"),
                meta.get("inact_color", "595959"),
                meta.get("angle", 180)
            )
        except Exception:
            pass

        try:
            full_colors = json.loads(cache_full.read_text())
            pywal.export.every(full_colors, output_dir=str(wal_dir))
            apply_kde_colors(full_colors)
        except Exception:
            pass

        # Ensure no sequences file exists to hijack terminals
        (wal_dir / "sequences").unlink(missing_ok=True)

        print(f"[pywal_sync] Cache hit for {image_path.name}")
        notify_quickshell()
        return

    # --- 2. CACHE MISS: GENERATE COLORS ---
    print(f"[pywal_sync] Generating new palette for {image_path.name}...")
    cache_base.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            w, h = img.size

            # Downsample crops for fast, compute-efficient color extraction
            max_crop_w = 720
            scale = min(1.0, max_crop_w / max(1, w))
            target_w = max(1, int(w * scale))
            target_h = max(1, int(h * scale))

            full_tmp = cache_base / "tmp_full.png"
            top_tmp = cache_base / "tmp_top.png"
            bot_tmp = cache_base / "tmp_bot.png"

            if scale < 1.0:
                resized = img.resize((target_w, target_h), Image.Resampling.BILINEAR)
                resized.save(full_tmp, "PNG")
                resized.crop((0, 0, target_w, max(1, target_h // 2))).save(top_tmp, "PNG")
                resized.crop((0, target_h // 2, target_w, target_h)).save(bot_tmp, "PNG")
            else:
                img.save(full_tmp, "PNG")
                img.crop((0, 0, w, max(1, h // 2))).save(top_tmp, "PNG")
                img.crop((0, h // 2, w, h)).save(bot_tmp, "PNG")

        raw_full = safe_extract_colors(full_tmp)
        raw_top = safe_extract_colors(top_tmp)
        raw_bot = safe_extract_colors(bot_tmp)

        # Enhance palettes for dark-theme contrast, readability, and modern aesthetics
        c_full = enhance_dark_palette(raw_full, full_tmp)
        c_top = enhance_dark_palette(raw_top, top_tmp)
        c_bot = enhance_dark_palette(raw_bot, bot_tmp)

        # Cleanup temp PNGs
        for p in (full_tmp, top_tmp, bot_tmp):
            p.unlink(missing_ok=True)

        c_full["wallpaper"] = str(image_path)
        c_top["wallpaper"] = str(image_path)
        c_bot["wallpaper"] = str(image_path)

        # Compute border colors (gradient top-to-bottom)
        top_color = c_top["colors"].get("color4", "#33ccff").lstrip("#")
        bot_color = c_bot["colors"].get("color4", "#00ff99").lstrip("#")

        h_top, _, _ = hex_to_hls(top_color)
        h_bot, _, _ = hex_to_hls(bot_color)
        hue_diff = abs(h_top - h_bot)
        hue_diff = min(hue_diff, 1.0 - hue_diff)

        # If top and bottom accents are too close in hue, pick secondary accent for distinct gradient
        if hue_diff < 0.08:
            alt_bot = c_bot["colors"].get("color5", c_bot["colors"].get("color2", "#00ff99")).lstrip("#")
            h_alt, _, _ = hex_to_hls(alt_bot)
            alt_diff = abs(h_top - h_alt)
            alt_diff = min(alt_diff, 1.0 - alt_diff)
            if alt_diff > hue_diff:
                bot_color = alt_bot
            else:
                bot_color = c_bot["colors"].get("color2", "#00ff99").lstrip("#")

        # Inactive border uses muted outline color (color8) rather than invisible dark background
        inact_color = c_full["colors"].get("color8", "#595959").lstrip("#")

        meta = {
            "top_color": top_color,
            "bot_color": bot_color,
            "inact_color": inact_color,
            "angle": 180
        }

        # Save to cache
        atomic_write_text(cache_full, json.dumps(c_full, indent=4))
        atomic_write_text(cache_bar, json.dumps(c_top, indent=4))
        atomic_write_text(cache_dock, json.dumps(c_bot, indent=4))
        atomic_write_text(cache_meta, json.dumps(meta, indent=4))

        # Copy to wal directory
        atomic_copy(cache_full, wal_dir / "colors.json")
        atomic_copy(cache_bar, wal_dir / "colors-bar.json")
        atomic_copy(cache_dock, wal_dir / "colors-dock.json")

        # Export templates (NEVER send terminal sequences)
        try:
            pywal.export.every(c_full, output_dir=str(wal_dir))
        except Exception:
            pass

        # Ensure no sequences file exists to hijack terminals
        (wal_dir / "sequences").unlink(missing_ok=True)

        # Apply Hyprland border & KDE/Dolphin colors
        apply_hyprland_border(top_color, bot_color, inact_color, 180)
        apply_kde_colors(c_full)

        print(f"[pywal_sync] Generation completed and cached for {image_path.name}")
        notify_quickshell()

    except Exception as e:
        sys.stderr.write(f"Error generating pywal colors: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
