#!/usr/bin/env python3
"""Shared frame capture + OCR glue for the x11-ocr scripts.

Captures the Linux desktop with spectacle (KDE) or ImageMagick import, OCRs
it with RapidOCR (x11_ocr.vision), and exposes click helpers. Coordinates are
full-resolution screen pixels, the same space xdotool works in.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FRAME_DIR = Path(tempfile.gettempdir()) / "x11-ocr"
# 1280x720 tiles: RapidOCR's det caps its longest side at 1280, so tiles this
# size are OCR'd at native resolution (no internal downscale).
TILE_W, TILE_H, TILE_OVERLAP = 1280, 720, 64


class CaptureError(RuntimeError):
    """Frame capture or OCR setup failed; the message says what to do."""


def resolve_display() -> str:
    """DISPLAY from env, else the first X socket in /tmp/.X11-unix (sets env)."""
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    for sock in sorted(Path("/tmp/.X11-unix").glob("X[0-9]*")):
        os.environ["DISPLAY"] = ":" + sock.name[1:]
        return os.environ["DISPLAY"]
    raise CaptureError("no DISPLAY in environment and no sockets in /tmp/.X11-unix")


def resolve_xauth() -> str:
    """XAUTHORITY from env; else the running Xserver's auth file.

    Picks the first /run/user/<uid>/xauth_* (Xwayland's -auth), then
    ~/.Xauthority. Sets the env var so xdotool/spectacle children inherit it."""
    if os.environ.get("XAUTHORITY") and Path(os.environ["XAUTHORITY"]).exists():
        return os.environ["XAUTHORITY"]
    candidates = []
    run_dir = Path("/run/user") / str(os.getuid())
    if run_dir.exists():
        candidates += sorted(run_dir.glob("xauth_*"))
    candidates.append(Path.home() / ".Xauthority")
    for cand in candidates:
        if cand.is_file():
            os.environ["XAUTHORITY"] = str(cand)
            return os.environ["XAUTHORITY"]
    raise CaptureError("no usable XAUTHORITY found (checked /run/user/*/xauth_* and ~/.Xauthority)")


def grab_frame(path: str | None = None):
    """Capture the full desktop (all monitors, includes menus/popups).

    Returns (PIL Image, RGB, frame Path, sha12)."""
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    frame_path = Path(path) if path else FRAME_DIR / "frame.png"
    frame_path.parent.mkdir(parents=True, exist_ok=True)

    def _fresh(p: Path) -> bool:
        return p.exists() and p.stat().st_size > 0

    ok, cmd, r = False, None, None
    if shutil.which("spectacle"):
        cmd = ["spectacle", "-b", "-f", "-n", "-o", str(frame_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0 and _fresh(frame_path)
    if not ok and shutil.which("import"):
        cmd = ["import", "-window", "root", str(frame_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0 and _fresh(frame_path)
    if not ok:
        err = (r.stderr.strip() or r.stdout.strip()) if r else "no capture tool found"
        raise CaptureError(f"frame capture failed ({cmd[0] if cmd else '?'}): {err}")

    from PIL import Image
    img = Image.open(frame_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    sha = hashlib.sha256(img.tobytes()).hexdigest()[:12]
    return img, frame_path, sha


def ocr_frame(img, sha: str, letters: bool = False, min_score: float = 0.45,
              window: tuple | None = None):
    """OCR a captured frame into the element tree.

    OCR runs on native-resolution tiles (1280x720 with overlap): RapidOCR's
    det model internally caps its longest side at 1280, so on a wide
    multi-monitor composite a full-frame pass would be downscaled and small
    dialog text becomes unreadable. Tiles keep text at 1:1 px density.

    window: optional (x, y, w, h) screen rect. The crop is OCR'd instead of
    the whole desktop (much faster, less ambiguity); bboxes are translated
    back to screen pixels. Pass None for full-desktop tiling.

    Returns (tree dict, ocr_s). Tree: blocks -> lines -> words(/letters) with
    [x, y, w, h] bboxes in screen pixels."""
    try:
        from x11_ocr.vision import Engine, build_tree, quad_to_bbox
    except ImportError as e:
        raise CaptureError(
            f"cannot import x11_ocr.vision (numpy/PIL in this interpreter): {e}; "
            "run under a python with rapidocr-onnxruntime, Pillow and numpy installed") from e

    engine = Engine()
    w, h = img.width, img.height
    if window:
        wx, wy, ww, wh = window
        pad = 12
        ox, oy = max(0, wx - pad), max(0, wy - pad)
        ox1, oy1 = min(w, wx + ww + pad), min(h, wy + wh + pad)
        target = img.crop((ox, oy, ox1, oy1))
    else:
        ox, oy, target = 0, 0, img

    merged = []
    t0 = time.perf_counter()
    tw, th = TILE_W, TILE_H
    for ty in _tile_starts(target.height, th, TILE_OVERLAP):
        for tx in _tile_starts(target.width, tw, TILE_OVERLAP):
            res, _ = engine.run(target.crop((tx, ty, tx + tw, ty + th)), 1.0)
            for quad, text, score in res or []:
                quad = [[p[0] + ox + tx, p[1] + oy + ty] for p in quad]
                merged.append((quad, text, score))
    ocr_s = time.perf_counter() - t0
    merged = _dedup_lines(merged)

    tree = build_tree(merged, w, h, sha, time.time(), ocr_s * 1000,
                      letters=letters, min_score=min_score)
    tree["frame"]["tiles"] = 1 if window else len(_tile_starts(w, tw, TILE_OVERLAP)) * len(_tile_starts(h, th, TILE_OVERLAP))
    return tree, ocr_s


def _tile_starts(total: int, tile: int, overlap: int) -> list[int]:
    """Tile start offsets covering [0, total) at ~1:1 density, clamped at the tail."""
    starts = list(range(0, max(total - tile, 0) + 1, tile - overlap)) or [0]
    if starts[-1] != max(total - tile, 0):
        starts.append(max(total - tile, 0))
    return starts


def _dedup_lines(lines: list) -> list:
    """Drop tile-overlap duplicates: same text with centre within 12px."""
    from x11_ocr.vision import quad_to_bbox

    out: list = []
    for entry in lines:
        bb = quad_to_bbox(entry[0])
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        dup = False
        for i, (oq, ot, oscore) in enumerate(out):
            ob = quad_to_bbox(oq)
            if (ot == entry[1]
                    and abs((ob[0] + ob[2]) / 2 - cx) < 12
                    and abs((ob[1] + ob[3]) / 2 - cy) < 12):
                if entry[2] > oscore:
                    out[i] = entry
                dup = True
                break
        if not dup:
            out.append(entry)
    return out


def click(x: int, y: int, button: int = 1, clicks: int = 1) -> None:
    """xdotool move + click at absolute screen px. button: 1 left, 2 middle, 3 right."""
    argv = ["xdotool", "mousemove", str(int(x)), str(int(y)), "click"]
    if clicks != 1:
        argv += ["--repeat", str(clicks), "--delay", "150"]
    argv.append(str(button))
    r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise CaptureError(f"xdotool click failed: {r.stderr.strip()}")