#!/usr/bin/env python3
"""
Grid overlay for screenshots - enables Claude to identify click coordinates.

Usage:
    python3 grid_overlay.py /path/to/screenshot.png
    python3 grid_overlay.py --mouse /path/to/screenshot.png
    python3 grid_overlay.py --window WINDOW_ID [--padding 50] /path/to/fullscreen.png

Options:
    --mouse              Show current mouse position with crosshair marker
    --window WINDOW_ID   Crop to window region (use with full-screen screenshot)
    --padding N          Extra pixels around window to capture popups (default: 50)

Output:
    Creates /path/to/screenshot_grid.png with coordinate grid overlay.
    Grid labels show ABSOLUTE screen coordinates for clicking.

Grid uses edge rulers (labels along top/left borders) and adaptive sizing
so coordinates remain readable at any resolution, including multi-monitor.
"""

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# Claude's vision model scales images to approximately this max dimension
VISION_MAX_PX = 1568
# Minimum label height in vision pixels for readability
MIN_READABLE_PX = 8
# Target grid cell size in vision pixels for interpolation accuracy
TARGET_CELL_VISION_PX = 60


def get_mouse_position() -> tuple[int, int] | None:
    """Get current mouse position using xdotool."""
    try:
        result = subprocess.run(
            ["xdotool", "getmouselocation"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse: "x:655 y:69 screen:0 window:12345678"
            parts = result.stdout.strip().split()
            x = int(parts[0].split(":")[1])
            y = int(parts[1].split(":")[1])
            return (x, y)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, IndexError):
        pass
    return None


def get_window_geometry(window_id: str) -> tuple[int, int, int, int] | None:
    """Get window geometry (x, y, width, height) using xdotool."""
    try:
        result = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", window_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse: WINDOW=...\nX=...\nY=...\nWIDTH=...\nHEIGHT=...\nSCREEN=...
            values = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, val = line.split("=", 1)
                    values[key] = int(val)
            return (values["X"], values["Y"], values["WIDTH"], values["HEIGHT"])
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, KeyError):
        pass
    return None


def _compute_grid_params(width: int, height: int) -> dict:
    """Compute adaptive grid spacing and font size based on image dimensions.

    Ensures labels are readable and grid cells are usable after Claude's
    vision model scales the image down.
    """
    max_dim = max(width, height)
    vision_scale = min(1.0, VISION_MAX_PX / max_dim)

    # Font size: ensure at least MIN_READABLE_PX after scaling
    font_size = max(12, int(MIN_READABLE_PX / vision_scale))
    # Cap at reasonable size
    font_size = min(font_size, 36)

    # Grid spacing: ensure cells are at least TARGET_CELL_VISION_PX in vision pixels
    raw_spacing = TARGET_CELL_VISION_PX / vision_scale
    # Round to a clean number (50, 100, 150, 200, 250, 500, ...)
    clean_spacings = [50, 100, 150, 200, 250, 300, 400, 500]
    major_spacing = 100  # default
    for s in clean_spacings:
        if s >= raw_spacing:
            major_spacing = s
            break
    else:
        major_spacing = clean_spacings[-1]

    minor_spacing = major_spacing // 2

    # Ruler bar height (for edge labels)
    ruler_height = font_size + 8

    return {
        "font_size": font_size,
        "major_spacing": major_spacing,
        "minor_spacing": minor_spacing,
        "vision_scale": vision_scale,
        "ruler_height": ruler_height,
    }


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a monospace font at the given size, with fallbacks."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def add_grid_overlay(
    input_path: str,
    output_path: str = None,
    major_spacing: int = None,
    minor_spacing: int = None,
    mouse_pos: tuple[int, int] = None,
    crop_region: tuple[int, int, int, int] = None,
) -> str:
    """
    Add coordinate grid overlay to an image.

    Uses edge rulers (labels along top and left borders) instead of labels
    at every intersection. Grid spacing and font size adapt to image size
    so coordinates remain readable in Claude's vision model.

    Args:
        input_path: Path to input image
        output_path: Path for output (default: input_grid.png)
        major_spacing: Override pixels between major grid lines (auto if None)
        minor_spacing: Override pixels between minor grid lines (auto if None)
        mouse_pos: Optional (x, y) tuple to draw mouse cursor marker (absolute coords)
        crop_region: Optional (x, y, width, height) to crop before adding grid.
                     Grid labels will show ABSOLUTE screen coordinates.

    Returns:
        Path to output image
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_grid{input_path.suffix}"
    output_path = Path(output_path)

    # Load image
    img = Image.open(input_path)

    # Crop if region specified
    origin_x, origin_y = 0, 0
    if crop_region is not None:
        cx, cy, cw, ch = crop_region
        # Clamp to image bounds
        img_w, img_h = img.size
        x1 = max(0, cx)
        y1 = max(0, cy)
        x2 = min(img_w, cx + cw)
        y2 = min(img_h, cy + ch)
        img = img.crop((x1, y1, x2, y2))
        origin_x, origin_y = x1, y1

    content_w, content_h = img.size

    # Compute adaptive parameters
    params = _compute_grid_params(content_w, content_h)
    if major_spacing is None:
        major_spacing = params["major_spacing"]
    if minor_spacing is None:
        minor_spacing = params["minor_spacing"]
    font_size = params["font_size"]
    ruler_h = params["ruler_height"]

    font = _load_font(font_size)

    # Create new image with ruler margins (top and left)
    new_w = ruler_h + content_w
    new_h = ruler_h + content_h
    canvas = Image.new("RGB", (new_w, new_h), (30, 30, 30))
    # Paste original content offset by ruler margins
    canvas.paste(img, (ruler_h, ruler_h))

    draw = ImageDraw.Draw(canvas)

    # Colors
    major_color = (255, 60, 60)
    minor_color = (120, 60, 60)
    ruler_bg = (20, 20, 20)
    ruler_text = (255, 255, 0)  # Yellow
    ruler_tick = (255, 255, 0, 200)

    # Draw ruler backgrounds
    draw.rectangle([0, 0, new_w, ruler_h - 1], fill=ruler_bg)
    draw.rectangle([0, 0, ruler_h - 1, new_h], fill=ruler_bg)
    # Ruler border lines
    draw.line([(ruler_h, ruler_h), (new_w, ruler_h)], fill=(100, 100, 100), width=1)
    draw.line([(ruler_h, ruler_h), (ruler_h, new_h)], fill=(100, 100, 100), width=1)

    # --- Compute grid positions (in absolute screen coords) ---
    def first_grid_pos(origin, spacing):
        pos = (origin // spacing) * spacing
        if pos < origin:
            pos += spacing
        return pos

    # --- Draw minor grid lines on the content area ---
    minor_start_x = first_grid_pos(origin_x, minor_spacing)
    for abs_x in range(minor_start_x, origin_x + content_w, minor_spacing):
        if abs_x % major_spacing != 0:
            canvas_x = ruler_h + (abs_x - origin_x)
            draw.line([(canvas_x, ruler_h), (canvas_x, new_h)], fill=minor_color, width=1)

    minor_start_y = first_grid_pos(origin_y, minor_spacing)
    for abs_y in range(minor_start_y, origin_y + content_h, minor_spacing):
        if abs_y % major_spacing != 0:
            canvas_y = ruler_h + (abs_y - origin_y)
            draw.line([(ruler_h, canvas_y), (new_w, canvas_y)], fill=minor_color, width=1)

    # --- Draw major grid lines and ruler labels ---
    major_start_x = first_grid_pos(origin_x, major_spacing)
    for abs_x in range(major_start_x, origin_x + content_w, major_spacing):
        canvas_x = ruler_h + (abs_x - origin_x)
        # Grid line on content
        draw.line([(canvas_x, ruler_h), (canvas_x, new_h)], fill=major_color, width=1)
        # Tick mark on ruler
        draw.line([(canvas_x, ruler_h - 6), (canvas_x, ruler_h)], fill=ruler_tick, width=2)
        # Label on top ruler
        label = str(abs_x)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        lx = canvas_x - tw // 2
        # Clamp label within ruler area
        lx = max(ruler_h + 2, min(lx, new_w - tw - 2))
        draw.text((lx, 2), label, fill=ruler_text, font=font)

    major_start_y = first_grid_pos(origin_y, major_spacing)
    for abs_y in range(major_start_y, origin_y + content_h, major_spacing):
        canvas_y = ruler_h + (abs_y - origin_y)
        # Grid line on content
        draw.line([(ruler_h, canvas_y), (new_w, canvas_y)], fill=major_color, width=1)
        # Tick mark on ruler
        draw.line([(ruler_h - 6, canvas_y), (ruler_h, canvas_y)], fill=ruler_tick, width=2)
        # Label on left ruler (rotated or horizontal)
        label = str(abs_y)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        ly = canvas_y - th // 2
        lx = ruler_h - tw - 4
        lx = max(2, lx)
        ly = max(ruler_h + 2, min(ly, new_h - th - 2))
        draw.text((lx, ly), label, fill=ruler_text, font=font)

    # --- Origin indicator (when cropped) ---
    if origin_x > 0 or origin_y > 0:
        origin_label = f"{origin_x},{origin_y}"
        bbox = draw.textbbox((0, 0), origin_label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        # Draw in the top-left corner square where rulers meet
        draw.rectangle([0, 0, ruler_h - 1, ruler_h - 1], fill=(0, 0, 100))
        # Center the text
        ox = max(1, (ruler_h - tw) // 2)
        oy = max(1, (ruler_h - th) // 2)
        draw.text((ox, oy), origin_label, fill=(200, 200, 255), font=font)

    # --- Mouse position marker ---
    if mouse_pos is not None:
        abs_mx, abs_my = mouse_pos
        # Convert to canvas coordinates
        mx = ruler_h + (abs_mx - origin_x)
        my = ruler_h + (abs_my - origin_y)
        if ruler_h <= mx < new_w and ruler_h <= my < new_h:
            cursor_color = (0, 255, 0)
            crosshair_size = max(20, font_size)

            # Draw crosshair
            draw.line([(mx - crosshair_size, my), (mx + crosshair_size, my)], fill=cursor_color, width=2)
            draw.line([(mx, my - crosshair_size), (mx, my + crosshair_size)], fill=cursor_color, width=2)

            # Draw circle around cursor
            circle_radius = max(8, font_size // 2)
            draw.ellipse(
                [mx - circle_radius, my - circle_radius, mx + circle_radius, my + circle_radius],
                outline=cursor_color,
                width=2,
            )

            # Draw coordinate label for mouse position
            mouse_label = f"MOUSE: {abs_mx},{abs_my}"
            bbox = draw.textbbox((0, 0), mouse_label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            label_x = mx + crosshair_size + 4
            label_y = my - th - 4
            if label_x + tw > new_w:
                label_x = mx - tw - crosshair_size - 4
            if label_y < ruler_h:
                label_y = my + crosshair_size + 4

            pad = 2
            draw.rectangle(
                [label_x - pad, label_y - pad, label_x + tw + pad, label_y + th + pad],
                fill=(0, 80, 0),
            )
            draw.text((label_x, label_y), mouse_label, fill=(255, 255, 255), font=font)

            # Also draw ruler highlight lines to the mouse position
            # Vertical line from top ruler to mouse
            draw.line([(mx, 0), (mx, ruler_h)], fill=cursor_color, width=2)
            # Horizontal line from left ruler to mouse
            draw.line([(0, my), (ruler_h, my)], fill=cursor_color, width=2)

    # Save output
    canvas.save(output_path)

    # Print diagnostic info
    print(f"Grid params: spacing={major_spacing}px, font={font_size}px, "
          f"vision_scale={params['vision_scale']:.2f}, "
          f"cell_in_vision={major_spacing * params['vision_scale']:.0f}px")

    return str(output_path)


def main():
    args = sys.argv[1:]
    show_mouse = False
    window_id = None
    padding = 50

    # Parse flags
    if "--mouse" in args:
        show_mouse = True
        args.remove("--mouse")

    if "--window" in args:
        idx = args.index("--window")
        if idx + 1 < len(args):
            window_id = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            print("Error: --window requires a WINDOW_ID argument", file=sys.stderr)
            sys.exit(1)

    if "--padding" in args:
        idx = args.index("--padding")
        if idx + 1 < len(args):
            try:
                padding = int(args[idx + 1])
            except ValueError:
                print("Error: --padding requires an integer argument", file=sys.stderr)
                sys.exit(1)
            args = args[:idx] + args[idx + 2:]
        else:
            print("Error: --padding requires an integer argument", file=sys.stderr)
            sys.exit(1)

    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [options] <screenshot.png> [output.png]", file=sys.stderr)
        print("\nAdds coordinate grid overlay to screenshot for identifying click positions.")
        print("\nOptions:")
        print("  --mouse              Show current mouse position with crosshair marker")
        print("  --window WINDOW_ID   Crop to window region (captures popups too)")
        print("  --padding N          Pixels around window for popups (default: 50)")
        sys.exit(1)

    input_path = args[0]
    output_path = args[1] if len(args) > 1 else None

    if not Path(input_path).exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Get mouse position if requested
    mouse_pos = None
    if show_mouse:
        mouse_pos = get_mouse_position()
        if mouse_pos:
            print(f"Mouse position: {mouse_pos[0]},{mouse_pos[1]}")
        else:
            print("Warning: Could not get mouse position (xdotool missing or no DISPLAY?)", file=sys.stderr)

    # Get window crop region if requested
    crop_region = None
    if window_id:
        geom = get_window_geometry(window_id)
        if geom:
            wx, wy, ww, wh = geom
            # Add padding for popups
            crop_region = (wx - padding, wy - padding, ww + 2 * padding, wh + 2 * padding)
            print(f"Window geometry: {wx},{wy} {ww}x{wh} (padding: {padding})")
        else:
            print(f"Warning: Could not get geometry for window {window_id}", file=sys.stderr)

    result = add_grid_overlay(input_path, output_path, mouse_pos=mouse_pos, crop_region=crop_region)
    print(f"Grid overlay created: {result}")


if __name__ == "__main__":
    main()
