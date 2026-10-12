#!/usr/bin/env python3
"""List application windows with geometry via AT-SPI (works on Wayland and X11).

wmctrl/xdotool search only see X11 (Xwayland) windows; this enumerates the
compositor's real window list from the accessibility tree, which covers
Wayland-native apps too (kdialog, kate, konsole, ...).

Usage:
    windows.py                 # JSON list of all windows
    windows.py kdialog         # only windows whose app/title contains the string
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from x11_ocr.framegrab import CaptureError

WINDOW_ROLES = {"frame", "dialog", "window", "notification", "splash screen"}

# Set while the subprocess fallback below is running, so a system python
# without gi raises instead of recursing forever.
_SUB_GUARD = "_X11OCR_WINDOWS_CHILD"


class _NoAtspi(Exception):
    """python3-gi not importable in this interpreter."""


def _atspi():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        return Atspi
    except (ImportError, ValueError) as e:
        raise _NoAtspi(str(e)) from e


# System python is where gir1.2-atspi-2.0 (gi) typically lives. Override with
# X11OCR_SYSTEM_PYTHON when a different interpreter holds the gi bindings.
_SHELL_PY = os.environ.get("X11OCR_SYSTEM_PYTHON", "/usr/bin/python3")


def _child_env() -> dict:
    """Env for the fallback subprocess: the recursion guard, plus PYTHONPATH
    pointing at the folder that contains this x11_ocr package, so the system
    python can import it from a repo checkout or a venv's site-packages."""
    env = dict(os.environ)
    env[_SUB_GUARD] = "1"
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    existing = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([pkg_parent] + existing)
    return env


def list_windows(app_query: str | None = None) -> list[dict]:
    """Window list over AT-SPI; falls back to the system python when the
    calling interpreter (e.g. a venv) has no gi bindings."""
    try:
        return _list_windows_atspi(app_query)
    except _NoAtspi:
        if os.environ.get(_SUB_GUARD):
            raise CaptureError(
                f"no gi bindings here and {_SHELL_PY} fallback also lacks them")
        env = _child_env()
        env.setdefault("DISPLAY", ":0")
        r = subprocess.run(
            [_SHELL_PY, str(Path(__file__).resolve()), "--json", app_query or ""],
            capture_output=True, text=True, timeout=20, env=env)
        if r.returncode != 0:
            raise CaptureError(f"windows.py fallback failed: {r.stderr.strip()}")
        return json.loads(r.stdout)


def _list_windows_atspi(app_query: str | None = None) -> list[dict]:
    Atspi = _atspi()
    desktop = Atspi.get_desktop(0)
    out = []
    q = app_query.casefold() if app_query else None
    seen = set()
    for ai in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(ai)
        if app is None:
            continue
        app_name = ""
        try:
            app_name = app.get_name() or ""
        except Exception:
            pass
        for wi in range(app.get_child_count()):
            win = app.get_child_at_index(wi)
            if win is None:
                continue
            role = title = ""
            try:
                role = Atspi.Role.get_name(win.get_role()).casefold()
                title = win.get_name() or ""
            except Exception:
                continue
            if role not in WINDOW_ROLES and win.get_child_count() == 0:
                continue
            rect = None
            try:
                r = Atspi.Component.get_extents(win, Atspi.CoordType.SCREEN)
                if r.width <= 0 or r.height <= 0:
                    continue
                rect = {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
            except Exception:
                continue
            pid = 0
            try:
                pid = app.get_process_id() or 0
            except Exception:
                pass
            key = (app_name, title, rect["x"], rect["y"])
            if key in seen or (q and q not in app_name.casefold() and q not in title.casefold()):
                continue
            seen.add(key)
            out.append({"app": app_name, "title": title, "pid": pid,
                        "x": rect["x"], "y": rect["y"], "w": rect["w"], "h": rect["h"]})
    return out


def find_window(query: str) -> tuple:
    """First window whose app or title contains query (case-insensitive).

    Returns (dict, all_matches); raises CaptureError when nothing matches."""
    wins = [w for w in list_windows() if query.casefold() in (w["app"] + " " + w["title"]).casefold()]
    if not wins:
        raise CaptureError(f"no window matching {query!r} (see windows.py for candidates)")
    return wins[0], wins


def press_at(x: int, y: int, app_query: str | None = None) -> dict:
    """Trigger the actionable AT-SPI node containing (x, y) (screen px).

    The app presses its own button/menu item/link, which works for both
    X11 and Wayland-native windows (xdotool pointer events do not reach
    most apps on Plasma Wayland; keyboard and AT-SPI actions do).

    Returns {method, app, role, name, action, x, y} of the pressed node.
    Raises CaptureError when nothing actionable is found."""
    try:
        return _press_local(x, y, app_query)
    except _NoAtspi as e:
        return _press_subprocess(x, y, app_query or "", str(e))


def _press_subprocess(x, y, app_query: str, why: str) -> dict:
    """Run the press under the system python (interpreters like script venvs
    have no gi bindings)."""
    if os.environ.get(_SUB_GUARD):
        raise CaptureError(f"{why} and {_SHELL_PY} fallback also lacks gi")
    r = subprocess.run(
        [_SHELL_PY, str(Path(__file__).resolve()), "--press", str(x), str(y), app_query],
        capture_output=True, text=True, timeout=30, env=_child_env())
    if r.returncode == 0:
        return json.loads(r.stdout)
    detail = r.stderr.strip()
    try:
        detail = json.loads(r.stdout)["error"]
    except Exception:
        pass
    raise CaptureError(f"atspi press failed ({why}): {detail}")


def _press_local(x: int, y: int, app_query: str | None) -> dict:
    Atspi = _atspi()
    desktop = Atspi.get_desktop(0)
    best = None
    best_node = None
    seen = 0
    for ai in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(ai)
        try:
            app_name = app.get_name() or ""
        except Exception:
            continue
        if app_query and app_query.casefold() not in app_name.casefold():
            continue

        def walk(node, depth):
            nonlocal best, best_node, seen
            if node is None or depth > 12 or seen > 20000:
                return
            seen += 1
            try:
                r = Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN)
                if r.x <= x < r.x + r.width and r.y <= y < r.y + r.height:
                    n = Atspi.Action.get_n_actions(node) or 0
                    if n > 0:
                        area = (r.width or 1) * (r.height or 1)
                        if best is None or area < best["area"]:
                            best = {
                                "app": app_name,
                                "role": Atspi.Role.get_name(node.get_role()),
                                "name": node.get_name() or "",
                                "area": area,
                                "action": Atspi.Action.get_action_name(node, 0),
                            }
                            best_node = node
            except Exception:
                return
            for i in range(node.get_child_count()):
                walk(node.get_child_at_index(i), depth + 1)

        for wi in range(app.get_child_count()):
            walk(app.get_child_at_index(wi), 0)
    if best is None or best_node is None:
        raise CaptureError(f"no actionable AT-SPI node contains ({x},{y})")
    if not Atspi.Action.do_action(best_node, 0):
        raise CaptureError(f"do_action failed on {best['name']!r}")
    result = {k: v for k, v in best.items() if k != "area"}
    result["ok"] = True
    result["method"] = "atspi"
    result["x"], result["y"] = x, y
    return result


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--press":
        x, y = int(argv[1]), int(argv[2])
        q = argv[3] if len(argv) > 3 and argv[3] else None
        try:
            print(json.dumps(_press_local(x, y, q), ensure_ascii=False))
        except CaptureError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        return
    argv = [a for a in argv if a != "--json"]
    q = argv[0] if argv and argv[0] else None
    print(json.dumps(list_windows(q), ensure_ascii=False))


if __name__ == "__main__":
    main()