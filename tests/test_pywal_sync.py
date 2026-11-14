import unittest
import tempfile
import shutil
import json
import os
import colorsys
from pathlib import Path
from PIL import Image

# Import pywal_sync module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import pywal_sync


def hex_to_srgb(hex_str):
    hex_str = hex_str.lstrip("#")
    return [int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4)]


def relative_luminance(rgb):
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [channel(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex1, hex2):
    l1 = relative_luminance(hex_to_srgb(hex1))
    l2 = relative_luminance(hex_to_srgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


class TestPywalSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Save actual wallpaper path to restore after tests
        cls.last_wp_file = Path.home() / ".cache" / "wallpaper_picker" / "last_wallpaper"
        cls.real_wallpaper = None
        if cls.last_wp_file.is_file():
            line = cls.last_wp_file.read_text().strip()
            if "|" in line:
                cls.real_wallpaper = line.split("|", 1)[1].strip()
            elif line:
                cls.real_wallpaper = line

    @classmethod
    def tearDownClass(cls):
        # Always restore actual user wallpaper palette after running tests
        if cls.real_wallpaper and Path(cls.real_wallpaper).is_file():
            old_argv = sys.argv
            try:
                sys.argv = ["pywal_sync.py", cls.real_wallpaper]
                pywal_sync.main()
            finally:
                sys.argv = old_argv

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.img_path = Path(self.temp_dir) / "test_wallpaper.png"
        self.wal_dir = Path(self.temp_dir) / "wal"
        self.cache_base = Path(self.temp_dir) / "pywal_cache"
        self.hypr_lua = Path(self.temp_dir) / "colors.lua"

        self.old_env = os.environ.copy()
        os.environ["WAL_DIR"] = str(self.wal_dir)
        os.environ["WAL_CACHE_BASE_DIR"] = str(self.cache_base)
        os.environ["HYPR_COLORS_PATH"] = str(self.hypr_lua)
        os.environ["PYWAL_NO_HYPRCTL"] = "1"

        # Create a test gradient image: Top is orange/red, Bottom is blue/green
        img = Image.new("RGB", (200, 200))
        for y in range(100):
            for x in range(200):
                img.putpixel((x, y), (220, 80, 40)) # Warm top
        for y in range(100, 200):
            for x in range(200):
                img.putpixel((x, y), (40, 100, 200)) # Cool bottom
        img.save(self.img_path)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolve_image_path(self):
        # Existing file
        resolved = pywal_sync.resolve_image_path(str(self.img_path))
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved, self.img_path.resolve())

        # Nonexistent file
        none_resolved = pywal_sync.resolve_image_path(str(Path(self.temp_dir) / "missing.jpg"))
        self.assertIsNone(none_resolved)

    def test_compute_cache_key(self):
        k1 = pywal_sync.compute_cache_key(self.img_path)
        k2 = pywal_sync.compute_cache_key(self.img_path)
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 24)

    def test_enhance_dark_palette_contrast_and_darkness(self):
        # Test bright / harsh input palette
        bright_raw = {
            "special": {"background": "#ffffff", "foreground": "#111111"},
            "colors": {f"color{i}": "#ffaa55" for i in range(16)}
        }
        enhanced = pywal_sync.enhance_dark_palette(bright_raw)

        bg_hex = enhanced["special"]["background"]
        fg_hex = enhanced["special"]["foreground"]
        h_bg, l_bg, s_bg = pywal_sync.hex_to_hls(bg_hex)
        h_fg, l_fg, s_fg = pywal_sync.hex_to_hls(fg_hex)

        # Must be dark theme background
        self.assertLessEqual(l_bg, 0.12)
        # Must be light readable foreground
        self.assertGreaterEqual(l_fg, 0.88)
        # Must have high WCAG contrast
        ratio = contrast_ratio(fg_hex, bg_hex)
        self.assertGreater(ratio, 7.0)

    def test_pywal_sync_generation_and_caching(self):
        cache_key = pywal_sync.compute_cache_key(self.img_path)
        cache_dir = self.cache_base / cache_key

        # Run pywal_sync in isolated environment
        old_argv = sys.argv
        try:
            sys.argv = ["pywal_sync.py", str(self.img_path)]
            pywal_sync.main()
        finally:
            sys.argv = old_argv

        # Check that cache files were created in isolated cache
        self.assertTrue(cache_dir.exists())
        self.assertTrue((cache_dir / "colors.json").is_file())
        self.assertTrue((cache_dir / "colors-bar.json").is_file())
        self.assertTrue((cache_dir / "colors-dock.json").is_file())
        self.assertTrue((cache_dir / "meta.json").is_file())

        meta = json.loads((cache_dir / "meta.json").read_text())
        self.assertEqual(meta["angle"], 180)
        self.assertTrue(len(meta["top_color"]) > 0)
        self.assertTrue(len(meta["bot_color"]) > 0)
        # Inactive border must NOT be invisible dark background
        self.assertNotEqual(meta["inact_color"].lower(), "000000")

        # Verify deployed files in isolated wal directory
        self.assertTrue((self.wal_dir / "colors.json").is_file())
        self.assertTrue((self.wal_dir / "colors-bar.json").is_file())
        self.assertTrue((self.wal_dir / "colors-dock.json").is_file())

        # Verify that terminal sequences were NOT generated / dumped
        self.assertFalse((self.wal_dir / "sequences").is_file())

        # Verify dark theme and contrast in generated colors
        colors_bar = json.loads((self.wal_dir / "colors-bar.json").read_text())
        bg_hex = colors_bar["special"]["background"]
        fg_hex = colors_bar["special"]["foreground"]
        c4_hex = colors_bar["colors"]["color4"]
        c8_hex = colors_bar["colors"]["color8"]

        h_bg, l_bg, s_bg = pywal_sync.hex_to_hls(bg_hex)
        h_fg, l_fg, s_fg = pywal_sync.hex_to_hls(fg_hex)
        h_c4, l_c4, s_c4 = pywal_sync.hex_to_hls(c4_hex)

        self.assertLessEqual(l_bg, 0.12, "Background must be dark")
        self.assertGreaterEqual(l_fg, 0.88, "Foreground must be bright and legible")
        self.assertGreaterEqual(s_c4, 0.50, "Primary accent must be vibrant, not washed out")
        self.assertGreater(contrast_ratio(fg_hex, bg_hex), 7.0, "Foreground must have >= 7:1 contrast")

        # Inactive border contrast (color8 vs background) must be readable
        self.assertGreater(contrast_ratio(c8_hex, bg_hex), 3.0, "Inactive border outline must be visible")

        # Verify Hyprland colors.lua file exists in isolated path
        self.assertTrue(self.hypr_lua.is_file())
        content = self.hypr_lua.read_text()
        self.assertIn("col.active_border", content)
        self.assertIn("angle = 180", content)

        # Second run should be a cache hit
        old_argv = sys.argv
        try:
            sys.argv = ["pywal_sync.py", str(self.img_path)]
            pywal_sync.main()
        finally:
            sys.argv = old_argv

        self.assertTrue((cache_dir / "colors.json").is_file())

    def test_video_resolution_fallback(self):
        video_file = Path(self.temp_dir) / "test_video.mp4"
        video_file.write_text("fake video")
        
        thumb_dir = Path.home() / ".cache" / "wallpaper_picker" / "thumbs"
        fake_thumb = thumb_dir / f"000_{video_file.name}.jpg"
        shutil.copyfile(self.img_path, fake_thumb)

        resolved = pywal_sync.resolve_image_path(str(video_file))
        self.assertEqual(resolved, fake_thumb)

        if fake_thumb.exists():
            fake_thumb.unlink()

    def test_atomic_copy(self):
        src_file = Path(self.temp_dir) / "source.json"
        src_file.write_text('{"test": true}')
        dst_file = self.wal_dir / "target.json"

        pywal_sync.atomic_copy(src_file, dst_file)
        self.assertTrue(dst_file.is_file())
        self.assertEqual(json.loads(dst_file.read_text()), {"test": True})


if __name__ == "__main__":
    unittest.main()
