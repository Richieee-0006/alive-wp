# QS Wallpaper Picker (alive-wp)

Keyboard-first Quickshell wallpaper picker for Hyprland supporting local images, videos, color filtering, and Wallhaven search.

## Key Features
- **Image & Video Wallpapers:** Applies static/animated wallpapers via `awww` and video wallpapers via `mpvpaper`.
- **Color & Text Filtering:** Filters local wallpapers by extracted dominant colors or filename.
- **Wallhaven Discovery:** Searches Wallhaven with display-aspect ranking, preview caching, and validated full-resolution downloads.
- **Desktop Integrations:** Optional Matugen color generation and reload hooks for Waybar, Kitty, Cava, SwayNC, and SwayOSD.

## Tech Stack
- **UI & Shell:** Quickshell (QML), Bash
- **Backend & Media:** Python 3.12, ImageMagick, FFmpeg
- **Compositor:** Hyprland, `awww`, `mpvpaper`
