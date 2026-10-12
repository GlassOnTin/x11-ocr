#!/usr/bin/env python3
"""
Extract UI controls from a window using AT-SPI accessibility API.

Usage:
    python3 list_controls.py                     # List all applications
    python3 list_controls.py "App Name"          # List controls for app
    python3 list_controls.py "App Name" --tree   # Show full hierarchy
    python3 list_controls.py "App Name" --actionable  # Only clickable/editable

Requires: gir1.2-atspi-2.0 (usually pre-installed on desktop Linux)
"""

import sys

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except (ImportError, ValueError) as e:
    print(f"Error: AT-SPI bindings not available: {e}", file=sys.stderr)
    print("Try: sudo apt install gir1.2-atspi-2.0", file=sys.stderr)
    sys.exit(1)


def get_role_name(obj):
    """Get human-readable role name."""
    try:
        role = obj.get_role()
        return Atspi.Role.get_name(role)
    except Exception:
        return "unknown"


def get_name(obj):
    """Get accessible name."""
    try:
        return obj.get_name() or ""
    except Exception:
        return ""


def get_description(obj):
    """Get accessible description."""
    try:
        return obj.get_description() or ""
    except Exception:
        return ""


def get_states(obj):
    """Get state set as list of strings."""
    try:
        state_set = obj.get_state_set()
        states = []
        # Check common states
        state_checks = [
            (Atspi.StateType.FOCUSED, "focused"),
            (Atspi.StateType.SELECTED, "selected"),
            (Atspi.StateType.CHECKED, "checked"),
            (Atspi.StateType.EXPANDED, "expanded"),
            (Atspi.StateType.EDITABLE, "editable"),
            (Atspi.StateType.ENABLED, "enabled"),
            (Atspi.StateType.FOCUSABLE, "focusable"),
            (Atspi.StateType.SENSITIVE, "sensitive"),
            (Atspi.StateType.VISIBLE, "visible"),
            (Atspi.StateType.SHOWING, "showing"),
        ]
        for state_type, name in state_checks:
            if state_set.contains(state_type):
                states.append(name)
        return states
    except Exception:
        return []


def get_actions(obj):
    """Get available actions."""
    try:
        n_actions = Atspi.Action.get_n_actions(obj)
        return [Atspi.Action.get_action_name(obj, i) for i in range(n_actions)]
    except Exception:
        return []


def get_position(obj):
    """Get screen position and size."""
    try:
        rect = Atspi.Component.get_extents(obj, Atspi.CoordType.SCREEN)
        return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}
    except Exception:
        return None


def get_value(obj):
    """Get current value for text/numeric controls."""
    try:
        text = Atspi.Text.get_text(obj, 0, Atspi.Text.get_character_count(obj))
        if text:
            return text
    except Exception:
        pass
    try:
        return Atspi.Value.get_current_value(obj)
    except Exception:
        pass
    return None


def is_actionable(obj):
    """Check if control is actionable (clickable, editable, etc.)."""
    role_name = get_role_name(obj)
    actionable_roles = {
        "push button", "toggle button", "check box", "radio button",
        "menu item", "combo box", "text", "entry", "password text",
        "spin button", "slider", "link", "tree item", "list item",
        "tab", "page tab", "check menu item", "radio menu item"
    }
    if role_name in actionable_roles:
        return True
    actions = get_actions(obj)
    if actions:
        return True
    states = get_states(obj)
    if "focusable" in states or "editable" in states:
        return True
    return False


def format_control(obj, indent=0):
    """Format control info as string."""
    role = get_role_name(obj)
    name = get_name(obj)
    pos = get_position(obj)
    actions = get_actions(obj)
    states = get_states(obj)
    value = get_value(obj)

    prefix = "  " * indent
    parts = [f"{prefix}[{role}]"]

    if name:
        parts.append(f'"{name}"')

    if pos and pos["width"] > 0:
        parts.append(f"@ ({pos['x']},{pos['y']}) {pos['width']}x{pos['height']}")

    if actions:
        parts.append(f"actions={actions}")

    if value is not None and str(value).strip():
        val_str = str(value)[:50]
        if len(str(value)) > 50:
            val_str += "..."
        parts.append(f'value="{val_str}"')

    # Show key states
    key_states = [s for s in states if s in ("focused", "selected", "checked", "expanded", "editable")]
    if key_states:
        parts.append(f"({', '.join(key_states)})")

    return " ".join(parts)


def walk_tree(obj, indent=0, actionable_only=False, max_depth=20):
    """Recursively walk accessibility tree."""
    if indent > max_depth:
        return

    if actionable_only and not is_actionable(obj):
        # Still recurse into children
        pass
    else:
        print(format_control(obj, indent))

    try:
        for i in range(obj.get_child_count()):
            child = obj.get_child_at_index(i)
            if child:
                walk_tree(child, indent + 1, actionable_only, max_depth)
    except Exception:
        pass


def list_applications():
    """List all accessible applications."""
    desktop = Atspi.get_desktop(0)
    count = desktop.get_child_count()
    print(f"Found {count} accessible applications:\n")

    for i in range(count):
        app = desktop.get_child_at_index(i)
        if app:
            name = get_name(app) or "(unnamed)"
            try:
                pid = app.get_process_id()
                print(f"  [{i}] {name} (PID: {pid})")
            except Exception:
                print(f"  [{i}] {name}")


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


def main():
    args = sys.argv[1:]

    show_tree = "--tree" in args
    actionable_only = "--actionable" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        list_applications()
        print("\nUsage:")
        print("  python3 list_controls.py 'App Name'            # List actionable controls")
        print("  python3 list_controls.py 'App Name' --tree     # Full hierarchy")
        print("  python3 list_controls.py 'App Name' --actionable --tree  # Tree of actionable only")
        return

    app_name = args[0]
    app = find_application(app_name)

    if not app:
        print(f"Application '{app_name}' not found.", file=sys.stderr)
        print("\nAvailable applications:", file=sys.stderr)
        list_applications()
        sys.exit(1)

    print(f"Controls for: {get_name(app)}\n")

    if show_tree:
        walk_tree(app, actionable_only=actionable_only)
    else:
        # Flat list of actionable controls
        def collect_controls(obj, results):
            if is_actionable(obj):
                results.append(obj)
            try:
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        collect_controls(child, results)
            except Exception:
                pass

        controls = []
        collect_controls(app, controls)

        print(f"Found {len(controls)} actionable controls:\n")
        for ctrl in controls:
            print(format_control(ctrl))


if __name__ == "__main__":
    main()
