#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rembg[cpu]",
#     "opencv-python",
#     "pillow",
#     "numpy",
#     "onnxruntime",
# ]
# ///

import os
import sys
import json
import hashlib

def _atomic_write_json(path, data):
    import fcntl
    import tempfile

    lock_path = os.path.join(os.path.dirname(path), "index.lock")
    with open(lock_path, "w", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        idx = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    idx = json.load(f)
            except Exception:
                idx = {}
        idx.update(data)
        fd, tmp_name = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".index.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(idx, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def process_wallpaper(wall_path):
    if not os.path.isfile(wall_path):
        print(f"File not found: {wall_path}", file=sys.stderr)
        sys.exit(1)

    with open(wall_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()

    cache_dir = os.path.expanduser(f"~/.cache/wallpaper_picker/layers/{h}")
    os.makedirs(cache_dir, exist_ok=True)

    fg_path = os.path.join(cache_dir, "fg.png")
    bg_path = os.path.join(cache_dir, "bg.png")

    # Defer heavy CV/ONNX imports until layer generation is actually needed.
    if not os.path.isfile(fg_path) or not os.path.isfile(bg_path):
        import PIL.Image
        import PIL.ImageOps
        import numpy as np
        import cv2

        # 1. Generate FG cutout if missing
        if not os.path.isfile(fg_path):
            import rembg

            with PIL.Image.open(wall_path) as raw_img:
                img = PIL.ImageOps.exif_transpose(raw_img).convert("RGBA")
            session = rembg.new_session("u2net", providers=["CPUExecutionProvider"])
            fg_img = rembg.remove(img, session=session).convert("RGBA")

            fg_arr = np.array(fg_img)
            alpha_ch = fg_arr[:, :, 3]
            blurred_alpha = cv2.GaussianBlur(alpha_ch, (3, 3), 0)
            bin_mask = (alpha_ch > 128).astype(np.uint8)
            k3 = np.ones((3, 3), np.uint8)
            grad = cv2.dilate(bin_mask, k3) - cv2.erode(bin_mask, k3)
            boundary = ((alpha_ch > 0) & (alpha_ch < 255)) | (grad > 0)
            fg_arr[:, :, 3] = np.where(boundary, blurred_alpha, alpha_ch)
            PIL.Image.fromarray(fg_arr, "RGBA").save(fg_path)

        # 2. Generate BG inpainted if missing
        if not os.path.isfile(bg_path):
            with PIL.Image.open(wall_path) as raw_src:
                src_rgb = PIL.ImageOps.exif_transpose(raw_src).convert("RGB")
            src = cv2.cvtColor(np.array(src_rgb), cv2.COLOR_RGB2BGR)
            fg = cv2.imread(fg_path, cv2.IMREAD_UNCHANGED)
            if src is None or fg is None or fg.ndim < 3 or fg.shape[2] < 4:
                print(f"Invalid image or foreground mask for {wall_path}", file=sys.stderr)
                sys.exit(1)

            h_img, w_img = src.shape[:2]
            if h_img < 1 or w_img < 1:
                print(f"Invalid image dimensions for {wall_path}", file=sys.stderr)
                sys.exit(1)
            if fg.shape[:2] != (h_img, w_img):
                fg = cv2.resize(fg, (w_img, h_img), interpolation=cv2.INTER_LINEAR)

            alpha = fg[:, :, 3]
            kernel = np.ones((11, 11), np.uint8)
            mask = cv2.dilate((alpha > 128).astype(np.uint8) * 255, kernel, iterations=1)

            small_w = max(1, w_img // 2)
            small_h = max(1, h_img // 2)
            small_src = cv2.resize(src, (small_w, small_h))
            small_mask = cv2.resize(mask, (small_w, small_h))
            inpainted_small = cv2.inpaint(small_src, small_mask, 5, cv2.INPAINT_TELEA)
            inpainted_bg = cv2.resize(inpainted_small, (w_img, h_img))

            bg = np.where((mask > 0)[:, :, None], inpainted_bg, src)
            cv2.imwrite(bg_path, bg)

    # 3. Ensure depth.png exists before locking index.json to avoid deadlock with generate_depth.py
    depth_path = os.path.join(cache_dir, "depth.png")
    if not os.path.isfile(depth_path):
        try:
            import subprocess
            script_dir = os.path.dirname(os.path.abspath(__file__))
            res = subprocess.run(
                ["uv", "run", os.path.join(script_dir, "generate_depth.py"), wall_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode != 0:
                print(f"Warning: generate_depth.py failed ({res.returncode}): {res.stderr[-300:]}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: generate_depth.py error: {e}", file=sys.stderr)

    # 4. Update index.json atomically with file lock
    idx_path = os.path.expanduser("~/.cache/wallpaper_picker/layers/index.json")
    os.makedirs(os.path.dirname(idx_path), exist_ok=True)
    keys = {
        os.path.basename(wall_path),
        os.path.abspath(wall_path),
        os.path.realpath(wall_path),
    }
    updates = {}
    for k in keys:
        updates[k + ":fg"] = fg_path
        updates[k + ":bg"] = bg_path
        if os.path.isfile(depth_path):
            updates[k] = depth_path
    _atomic_write_json(idx_path, updates)

    print(fg_path)
    print(bg_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: generate_layers.py <image_path>", file=sys.stderr)
        sys.exit(1)
    process_wallpaper(sys.argv[1])
