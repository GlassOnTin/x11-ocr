#!/usr/bin/env python3
"""OCR the current desktop into a clickable element tree (JSON on stdout).

blocks -> lines -> words(/letters) with full-resolution pixel bboxes. The
captured frame PNG is saved and its path reported in the JSON, so the live
image can be viewed next to the tree.

Usage:
    screen_elements.py                 # whole tree
    screen_elements.py Settings        # only lines matching a substring
    screen_elements.py --letters       # per-letter boxes in words
    screen_elements.py --window code   # OCR one window only (faster, denser)
"""

from __future__ import annotations

import argparse
import json
import sys

from x11_ocr.framegrab import CaptureError, grab_frame, ocr_frame, resolve_display, resolve_xauth
from x11_ocr.windows import find_window


def filter_lines(tree: dict, query: str) -> dict:
    """Keep lines whose text contains query (case-insensitive); drop empty blocks."""
    q = query.casefold()
    for blk in tree["blocks"]:
        blk["lines"] = [ln for ln in blk["lines"] if q in ln["text"].casefold()]
    tree["blocks"] = [blk for blk in tree["blocks"] if blk["lines"]]
    tree["counts"] = {
        "blocks": len(tree["blocks"]),
        "lines": sum(len(b["lines"]) for b in tree["blocks"]),
    }
    return tree


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", nargs="?", help="keep only lines containing this substring")
    ap.add_argument("--letters", action="store_true", help="include per-letter boxes in words")
    ap.add_argument("--min-score", type=float, default=0.45, help="drop OCR lines below this score")
    ap.add_argument("--window", help="OCR only this window (AT-SPI app/title substring)")
    ap.add_argument("--out", help="frame PNG path (default /tmp/x11-ocr/frame.png)")
    args = ap.parse_args()

    try:
        resolve_display()
        resolve_xauth()
        win, _ = find_window(args.window) if args.window else (None, None)
        img, frame_path, sha = grab_frame(args.out)
        tree, ocr_ms = ocr_frame(img, sha, letters=args.letters, min_score=args.min_score,
                                 window=(win["x"], win["y"], win["w"], win["h"]) if win else None)
        if win:
            tree["frame"]["window"] = win
    except CaptureError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)

    tree["ok"] = True
    tree["frame"]["path"] = str(frame_path)
    if args.query:
        tree = filter_lines(tree, args.query)
    print(json.dumps(tree, ensure_ascii=False))


if __name__ == "__main__":
    main()