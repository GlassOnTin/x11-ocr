#!/usr/bin/env python3
"""
Detect popup dialogs and alerts using AT-SPI and X11.

Usage:
    python3 check_popups.py                    # Check all apps for dialogs
    python3 check_popups.py "AppName"          # Check specific app for dialogs
    python3 check_popups.py --watch "AppName"  # Watch for new popups (blocks)

Returns exit code 0 if no popups, 1 if popups found.
"""

import subprocess
import sys

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except (ImportError, ValueError) as e:
    print(f"Error: AT-SPI bindings not available: {e}", file=sys.stderr)
    sys.exit(2)


# Roles that indicate a popup/dialog
POPUP_ROLES = {
    "dialog", "alert", "file chooser", "color chooser",
    "font chooser", "message dialog", "error message",
    "warning message", "question message", "info message",
    "popup menu", "window",  # window can be a popup too
}


def get_position(obj):
    """Get screen position and size."""
    try:
        rect = Atspi.Component.get_extents(obj, Atspi.CoordType.SCREEN)
        return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}
    except Exception:
        return None


def get_name(obj):
    """Get accessible name."""
    try:
        return obj.get_name() or ""
    except Exception:
        return ""


def get_role_name(obj):
    """Get human-readable role name."""
    try:
        role = obj.get_role()
        return Atspi.Role.get_name(role)
    except Exception:
        return "unknown"


def get_states(obj):
    """Get state set as list of strings."""
    try:
        state_set = obj.get_state_set()
        states = []
        state_checks = [
            (Atspi.StateType.ACTIVE, "active"),
            (Atspi.StateType.MODAL, "modal"),
            (Atspi.StateType.VISIBLE, "visible"),
            (Atspi.StateType.SHOWING, "showing"),
        ]
        for state_type, name in state_checks:
            if state_set.contains(state_type):
                states.append(name)
        return states
    except Exception:
        return []


def find_popups_in_app(app):
    """Find popup/dialog windows in an application."""
    popups = []

    def check_node(obj, depth=0):
        if depth > 5:  # Don't go too deep
            return

        role = get_role_name(obj)
        name = get_name(obj)
        states = get_states(obj)

        # Check if this is a popup-like window
        is_popup = False

        if role in POPUP_ROLES:
            is_popup = True

        # Modal windows are definitely popups
        if "modal" in states:
            is_popup = True

        # Active dialog/frame that's not the main window
        if role in ("dialog", "alert", "frame") and "showing" in states:
            # Frames with short names or "warning/error" in name are likely popups
            if role != "frame" or any(kw in name.lower() for kw in ["warning", "error", "alert", "警告", "错误"]):
                is_popup = True

        if is_popup and "showing" in states:
            pos = get_position(obj)
            popups.append({
                "role": role,
                "name": name,
                "states": states,
                "position": pos,
                "obj": obj
            })

        # Check children
        try:
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    check_node(child, depth + 1)
        except Exception:
            pass

    check_node(app)
    return popups


def find_application(name_pattern):
    """Find application by name (case-insensitive partial match)."""
    desktop = Atspi.get_desktop(0)
    name_lower = name_pattern.lower()

    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app:
            app_name = get_name(app) or ""
            if name_lower in app_name.lower():
                return app
    return None


def check_all_apps():
    """Check all applications for popups."""
    desktop = Atspi.get_desktop(0)
    all_popups = []

    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app:
            app_name = get_name(app)
            popups = find_popups_in_app(app)
            for p in popups:
                p["app"] = app_name
                all_popups.append(p)

    return all_popups


def format_popup(popup):
    """Format popup info for display."""
    parts = [f"[{popup['role']}]"]

    if popup.get('app'):
        parts.append(f"app=\"{popup['app']}\"")

    if popup['name']:
        parts.append(f"\"{popup['name']}\"")

    if popup['position'] and popup['position']['width'] > 0:
        pos = popup['position']
        parts.append(f"@ ({pos['x']},{pos['y']}) {pos['width']}x{pos['height']}")

    if "modal" in popup['states']:
        parts.append("(MODAL)")

    return " ".join(parts)


def get_popup_buttons(popup):
    """Find buttons in a popup dialog."""
    buttons = []

    def find_buttons(obj):
        role = get_role_name(obj)
        if role == "push button":
            name = get_name(obj)
            pos = get_position(obj)
            if pos and pos['width'] > 0:
                buttons.append({"name": name, "position": pos})

        try:
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    find_buttons(child)
        except Exception:
            pass

    find_buttons(popup['obj'])
    return buttons


def main():
    args = sys.argv[1:]
    watch_mode = "--watch" in args
    if watch_mode:
        args.remove("--watch")

    app_name = args[0] if args else None

    if app_name:
        app = find_application(app_name)
        if not app:
            print(f"Application '{app_name}' not found.", file=sys.stderr)
            sys.exit(2)
        popups = find_popups_in_app(app)
        for p in popups:
            p["app"] = get_name(app)
    else:
        popups = check_all_apps()

    if popups:
        print(f"Found {len(popups)} popup(s):\n")
        for popup in popups:
            print(format_popup(popup))

            # Show buttons in the popup
            buttons = get_popup_buttons(popup)
            if buttons:
                print("  Buttons:")
                for btn in buttons:
                    pos = btn['position']
                    print(f"    [{btn['name']}] @ ({pos['x']},{pos['y']})")
            print()

        # Suggest dismissal
        print("To dismiss with keyboard: xdotool key Return  (or Escape)")
        sys.exit(1)
    else:
        print("No popups detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
