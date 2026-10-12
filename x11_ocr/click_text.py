#!/usr/bin/env python3
"""OCR the current desktop screen and click the text matching a query.

Requires a positive OCR match and never guesses coordinates: the match's own
pixel bbox provides the click position. With no match it exits 1 and prints
the lines it saw on screen.

Usage:
    click_text.py Settings             # first match, left click
    click_text.py "OK" --nth 1         # second match
    click_text.py Save --clicks 2      # double click
    click_text.py Save --dry-run       # report coords, no click
"""

from __future__ import annotations

import argparse
import json
import sys

from x11_ocr.framegrab import CaptureError, click, grab_frame, ocr_frame, resolve_display, resolve_xauth
from x11_ocr.vision import find_text
from x11_ocr.windows import find_window, press_at


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", help="text to click (case-insensitive substring unless --exact)")
    ap.add_argument("--nth", type=int, default=0, help="pick among matches, default first top-left")
    ap.add_argument("--exact", action="store_true", help="whole-node match instead of substring")
    ap.add_argument("--button", choices=["left", "middle", "right"], default="left")
    ap.add_argument("--clicks", type=int, default=1, help="1 single, 2 double")
    ap.add_argument("--dry-run", action="store_true", help="report target and coords, do not click")
    ap.add_argument("--method", choices=["auto", "atspi", "xdotool"], default="auto",
                    help="auto (default): AT-SPI press, fallback xdotool mouse; "
                         "atspi/xdotool force one mechanism (atspi is left click only)")
    ap.add_argument("--window", help="restrict the search to this window (AT-SPI app/title substring)")
    args = ap.parse_args()

    try:
        resolve_display()
        resolve_xauth()
        win, _ = find_window(args.window) if args.window else (None, [])
        img, frame_path, sha = grab_frame()
        tree, ocr_ms = ocr_frame(img, sha, window=(win["x"], win["y"], win["w"], win["h"]) if win else None)
    except CaptureError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)

    matches = find_text(tree, args.query, args.nth, args.exact)
    if not matches:
        lines = [ln["text"] for blk in tree["blocks"] for ln in blk["lines"]]
        out = {"ok": False, "query": args.query, "error": "no text match",
               "lines_on_screen": lines}
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(1)

    node = matches[0]
    x, y = (int(round(v)) for v in node["center"])
    button_id = {"left": 1, "middle": 2, "right": 3}[args.button]
    do_click = not args.dry_run
    result = {
        "ok": True, "query": args.query, "match": node, "x": x, "y": y,
        "button": args.button, "clicks": args.clicks,
        "clicked": do_click, "ocr_ms": round(ocr_ms, 1),
        "frame": {"path": str(frame_path), "sha12": sha,
                  "w": img.width, "h": img.height},
    }
    if do_click:
        try:
            method_used = _deliver(x, y, button_id, args.clicks, args.method,
                                   win["app"] if win else None)
            result["click_method"] = method_used
        except CaptureError as e:
            result["ok"] = False
            result["error"] = str(e)
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


def _deliver(x: int, y: int, button_id: int, clicks: int, method: str,
             app: str | None) -> str:
    """Send the click; returns the mechanism used.

    AT-SPI press first (works on Plasma Wayland and X11) unless a non-default
    button or multi-click is requested, then plain xdotool mouse events."""
    if method != "xdotool" and button_id == 1 and clicks == 1:
        try:
            press_at(x, y, app)
            return "atspi"
        except CaptureError as e:
            if method == "atspi":
                raise
            sys.stderr.write(f"note: atspi press unavailable ({e}); using xdotool\n")
    try:
        click(x, y, button_id, clicks)
        return "xdotool"
    except CaptureError:
        if method == "xdotool":
            raise
        raise CaptureError(
            f"both click mechanisms failed: no actionable AT-SPI node at ({x},{y}) "
            "and xdotool click did not deliver (Plasma Wayland limitation)")


if __name__ == "__main__":
    main()