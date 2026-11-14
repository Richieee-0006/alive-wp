#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "huggingface_hub",
#     "numpy",
#     "onnxruntime-gpu",
#     "pillow",
# ]
# ///
"""
generate_depth.py - Generates an 8-bit grayscale depth map for a wallpaper
using Depth Anything V2 (Small) ONNX.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image

HF_REPO_ID = "onnx-community/depth-anything-v2-small-ONNX"
MODEL_SUBFOLDER = "onnx"
MODEL_FILE = "model.onnx"
MODEL_DATA_FILE = "model.onnx_data"

CACHE_BASE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wallpaper_picker"
MODELS_DIR = CACHE_BASE / "models" / "depth_anything_v2_small"
LAYERS_DIR = CACHE_BASE / "layers"
INDEX_FILE = LAYERS_DIR / "index.json"


def _atomic_write_json(target_path: Path, data: dict):
    import os
    import tempfile

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target_path.parent), prefix=f".{target_path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def update_index(source_path: Path, depth_path: Path):
    import fcntl
    import os

    try:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = INDEX_FILE.parent / "index.lock"
        with open(lock_path, "w", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            index_data = {}
            if INDEX_FILE.exists():
                try:
                    with open(INDEX_FILE, "r", encoding="utf-8") as f:
                        index_data = json.load(f)
                except Exception:
                    index_data = {}
            abs_src = os.path.abspath(str(source_path))
            resolved_src = str(source_path.resolve())
            resolved_depth = str(depth_path.resolve())
            for k in {source_path.name, abs_src, resolved_src}:
                index_data[k] = resolved_depth
            _atomic_write_json(INDEX_FILE, index_data)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to update index.json: {e}\n")


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ensure_model() -> Path:
    """Ensures model and weights exist locally, downloading if necessary."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    local_model = MODELS_DIR / MODEL_FILE
    local_data = MODELS_DIR / MODEL_DATA_FILE

    if local_model.exists() and local_data.exists():
        return local_model

    from huggingface_hub import hf_hub_download

    sys.stderr.write(f"Downloading Depth Anything V2 ONNX weights from {HF_REPO_ID}...\n")
    m_path = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=f"{MODEL_SUBFOLDER}/{MODEL_FILE}",
        local_dir=str(MODELS_DIR),
        local_dir_use_symlinks=False,
    )
    # Move to root of MODELS_DIR if placed in subfolder
    m_path = Path(m_path)
    if m_path.name == MODEL_FILE and m_path.parent != MODELS_DIR:
        m_path.rename(local_model)

    d_path = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=f"{MODEL_SUBFOLDER}/{MODEL_DATA_FILE}",
        local_dir=str(MODELS_DIR),
        local_dir_use_symlinks=False,
    )
    d_path = Path(d_path)
    if d_path.name == MODEL_DATA_FILE and d_path.parent != MODELS_DIR:
        d_path.rename(local_data)

    return local_model


def preprocess(image: Image.Image, target_size=(518, 518)) -> tuple[np.ndarray, tuple[int, int]]:
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image)
    orig_w, orig_h = image.size
    img_rgb = image.convert("RGB")
    resized = img_rgb.resize(target_size, Image.Resampling.BICUBIC)

    # Normalize to ImageNet stats
    arr = np.array(resized, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    norm = (arr - mean) / std

    # [H, W, C] -> [1, C, H, W]
    blob = np.transpose(norm, (2, 0, 1))[np.newaxis, ...]
    return blob, (orig_w, orig_h)


def postprocess(raw_depth: np.ndarray, orig_size: tuple[int, int]) -> Image.Image:
    # Squeeze batch / channel dimensions
    depth = np.squeeze(raw_depth)
    d_min = depth.min()
    d_max = depth.max()
    denom = d_max - d_min
    if denom <= 0:
        denom = 1e-6

    # Normalize to 0..255 uint8
    norm = ((depth - d_min) / denom * 255.0).astype(np.uint8)
    depth_img = Image.fromarray(norm, mode="L")
    return depth_img.resize(orig_size, Image.Resampling.BILINEAR)


def run_depth(image_path: Path, output_path: Path, force=False) -> dict:
    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    img_hash = compute_sha256(image_path)
    layer_dir = LAYERS_DIR / img_hash
    layer_dir.mkdir(parents=True, exist_ok=True)
    target_out = output_path if output_path else (layer_dir / "depth.png")
    meta_out = layer_dir / "meta.json"

    if target_out.exists() and not force:
        update_index(image_path, target_out)
        return {
            "cached": True,
            "hash": img_hash,
            "depth_path": str(target_out),
            "meta_path": str(meta_out),
        }

    model_path = ensure_model()

    import onnxruntime as ort

    img = Image.open(image_path)
    blob, orig_size = preprocess(img)

    session_opts = ort.SessionOptions()
    session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    # Try CUDA first if available, fallback to CPU
    session = None
    used_provider = "CPUExecutionProvider"
    t0 = time.perf_counter()

    if os.environ.get("QS_DEPTH_USE_CUDA") == "1" and "CUDAExecutionProvider" in ort.get_available_providers():
        try:
            s = ort.InferenceSession(str(model_path), session_opts, providers=["CUDAExecutionProvider"])
            # Warmup test run to check cuDNN availability
            input_name = s.get_inputs()[0].name
            _ = s.run(None, {input_name: blob})
            session = s
            used_provider = "CUDAExecutionProvider"
        except Exception as e:
            sys.stderr.write(f"CUDA provider failed ({e}), falling back to CPUExecutionProvider...\n")

    if session is None:
        session = ort.InferenceSession(str(model_path), session_opts, providers=["CPUExecutionProvider"])
        used_provider = "CPUExecutionProvider"

    input_name = session.get_inputs()[0].name
    t_prep = time.perf_counter()
    preds = session.run(None, {input_name: blob})
    t_infer = time.perf_counter()

    depth_img = postprocess(preds[0], orig_size)
    depth_img.info.pop("icc_profile", None)
    target_out.parent.mkdir(parents=True, exist_ok=True)
    depth_img.save(target_out, "PNG", icc_profile=None, optimize=True)
    t_save = time.perf_counter()

    update_index(image_path, target_out)

    meta = {
        "cached": False,
        "hash": img_hash,
        "source": str(image_path.resolve()),
        "width": orig_size[0],
        "height": orig_size[1],
        "depth_path": str(target_out.resolve()),
        "provider": used_provider,
        "timings_ms": {
            "prep": round((t_prep - t0) * 1000, 2),
            "infer": round((t_infer - t_prep) * 1000, 2),
            "save": round((t_save - t_infer) * 1000, 2),
            "total": round((t_save - t0) * 1000, 2),
        },
    }

    _atomic_write_json(meta_out, meta)

    return meta


def main():
    parser = argparse.ArgumentParser(description="Generate depth map using Depth Anything V2 ONNX")
    parser.add_argument("image", type=Path, help="Input wallpaper path")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output depth map path")
    parser.add_argument("--force", "-f", action="store_true", help="Force recalculate depth map")
    parser.add_argument("--json", action="store_true", help="Output JSON metadata")
    args = parser.parse_args()

    meta = run_depth(args.image, args.output, force=args.force)

    if args.json:
        print(json.dumps(meta, indent=2))
    else:
        print(meta["depth_path"])


if __name__ == "__main__":
    main()
