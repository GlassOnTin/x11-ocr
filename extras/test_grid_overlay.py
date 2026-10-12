#!/usr/bin/env python3
"""
Test grid_overlay.py coordinate accuracy.

Creates synthetic test images with known target positions,
applies the grid overlay, then verifies the grid labels
correspond to correct click coordinates.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent))
from grid_overlay import add_grid_overlay, _compute_grid_params


def make_test_image(width: int, height: int, targets: list[tuple[int, int, str]] = None) -> Image.Image:
    """Create a test image with colored target markers at known positions."""
    img = Image.new("RGB", (width, height), (40, 40, 40))
    draw = ImageDraw.Draw(img)

    if targets:
        for tx, ty, label in targets:
            r = 15
            draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=(0, 200, 0), outline=(255, 255, 255), width=2)
            draw.line([(tx - r, ty), (tx + r, ty)], fill=(255, 255, 255), width=1)
            draw.line([(tx, ty - r), (tx, ty + r)], fill=(255, 255, 255), width=1)
            draw.text((tx + r + 3, ty - 6), f"{label} ({tx},{ty})", fill=(255, 255, 255))

    return img


def verify_grid_lines_on_canvas(grid_img: Image.Image, origin_x: int, origin_y: int,
                                  ruler_h: int, major_spacing: int = 100,
                                  content_w: int = 0, content_h: int = 0) -> list[dict]:
    """Verify grid lines are drawn at correct canvas positions.

    Grid lines are drawn on the content area, offset by ruler_h from the canvas origin.
    """
    width, height = grid_img.size
    results = []

    # Calculate first major grid position
    def first_grid_pos(origin, spacing):
        pos = (origin // spacing) * spacing
        if pos < origin:
            pos += spacing
        return pos

    # Check vertical grid lines
    start_abs_x = first_grid_pos(origin_x, major_spacing)
    for abs_x in range(start_abs_x, origin_x + content_w, major_spacing):
        canvas_x = ruler_h + (abs_x - origin_x)
        if 0 <= canvas_x < width:
            red_count = 0
            # Sample points in the content area (below ruler)
            sample_ys = [ruler_h + content_h // 4, ruler_h + content_h // 2, ruler_h + 3 * content_h // 4]
            for sy in sample_ys:
                if sy < height:
                    pixel = grid_img.getpixel((canvas_x, sy))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    if r > 200 and g < 100 and b < 100:
                        red_count += 1

            results.append({
                "type": "vertical",
                "abs_coord": abs_x,
                "canvas_pixel": canvas_x,
                "red_pixels_found": red_count,
                "pass": red_count >= 2,
            })

    # Check horizontal grid lines
    start_abs_y = first_grid_pos(origin_y, major_spacing)
    for abs_y in range(start_abs_y, origin_y + content_h, major_spacing):
        canvas_y = ruler_h + (abs_y - origin_y)
        if 0 <= canvas_y < height:
            red_count = 0
            sample_xs = [ruler_h + content_w // 4, ruler_h + content_w // 2, ruler_h + 3 * content_w // 4]
            for sx in sample_xs:
                if sx < width:
                    pixel = grid_img.getpixel((sx, canvas_y))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    if r > 200 and g < 100 and b < 100:
                        red_count += 1

            results.append({
                "type": "horizontal",
                "abs_coord": abs_y,
                "canvas_pixel": canvas_y,
                "red_pixels_found": red_count,
                "pass": red_count >= 2,
            })

    return results


def verify_ruler_labels(grid_img: Image.Image, origin_x: int, origin_y: int,
                         ruler_h: int, major_spacing: int, content_w: int, content_h: int) -> dict:
    """Verify ruler labels exist (yellow pixels in ruler area)."""
    width, height = grid_img.size

    # Check top ruler for yellow text near each grid line position
    top_ruler_yellow = 0
    def first_grid_pos(origin, spacing):
        pos = (origin // spacing) * spacing
        if pos < origin:
            pos += spacing
        return pos

    start_x = first_grid_pos(origin_x, major_spacing)
    n_expected_x = 0
    for abs_x in range(start_x, origin_x + content_w, major_spacing):
        canvas_x = ruler_h + (abs_x - origin_x)
        n_expected_x += 1
        # Search a ±30px region around expected position in top ruler
        for dx in range(-30, 31, 5):
            px = canvas_x + dx
            if 0 <= px < width:
                for py in range(0, ruler_h):
                    pixel = grid_img.getpixel((px, py))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    if r > 200 and g > 200 and b < 100:  # Yellow
                        top_ruler_yellow += 1
                        break

    # Check left ruler for yellow text
    left_ruler_yellow = 0
    start_y = first_grid_pos(origin_y, major_spacing)
    n_expected_y = 0
    for abs_y in range(start_y, origin_y + content_h, major_spacing):
        canvas_y = ruler_h + (abs_y - origin_y)
        n_expected_y += 1
        for dy in range(-30, 31, 5):
            py = canvas_y + dy
            if 0 <= py < height:
                for px in range(0, ruler_h):
                    pixel = grid_img.getpixel((px, py))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    if r > 200 and g > 200 and b < 100:
                        left_ruler_yellow += 1
                        break

    return {
        "top_ruler_yellow_regions": top_ruler_yellow,
        "left_ruler_yellow_regions": left_ruler_yellow,
        "expected_x_labels": n_expected_x,
        "expected_y_labels": n_expected_y,
        "top_has_labels": top_ruler_yellow > 0,
        "left_has_labels": left_ruler_yellow > 0,
    }


def test_adaptive_params():
    """Test: _compute_grid_params returns sensible values for various sizes."""
    print("=" * 60)
    print("TEST: Adaptive grid parameters")
    print("=" * 60)

    cases = [
        (800, 600, "Small window"),
        (1920, 1080, "HD monitor"),
        (2560, 1440, "QHD monitor"),
        (4480, 1440, "Dual QHD+HD"),
        (3840, 2160, "4K monitor"),
    ]

    all_pass = True
    for w, h, desc in cases:
        p = _compute_grid_params(w, h)
        vs = p["vision_scale"]
        fs = p["font_size"]
        ms = p["major_spacing"]
        cell_vis = ms * vs
        label_vis = fs * vs

        ok_label = label_vis >= 6
        ok_cell = cell_vis >= 30

        print(f"  {desc} ({w}x{h}):")
        print(f"    spacing={ms}px, font={fs}px, scale={vs:.3f}")
        print(f"    label_in_vision={label_vis:.1f}px {'OK' if ok_label else 'TOO SMALL'}")
        print(f"    cell_in_vision={cell_vis:.0f}px {'OK' if ok_cell else 'TOO SMALL'}")

        if not ok_label or not ok_cell:
            all_pass = False

    print(f"  RESULT: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


def test_basic_fullscreen():
    """Test: full-screen image, no crop. Grid lines at correct positions."""
    print("=" * 60)
    print("TEST: Basic full-screen (1920x1080, no crop)")
    print("=" * 60)

    content_w, content_h = 1920, 1080
    targets = [
        (150, 250, "A"),
        (500, 300, "B"),
        (1000, 700, "C"),
    ]

    img = make_test_image(content_w, content_h, targets)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")
    add_grid_overlay(input_path, output_path)

    grid_img = Image.open(output_path)
    params = _compute_grid_params(content_w, content_h)
    ruler_h = params["ruler_height"]
    major_spacing = params["major_spacing"]

    # Canvas should be larger than content by ruler margins
    expected_w = ruler_h + content_w
    expected_h = ruler_h + content_h
    assert grid_img.size == (expected_w, expected_h), f"Size: {grid_img.size} expected ({expected_w},{expected_h})"
    print(f"  Canvas size: {grid_img.size} (content {content_w}x{content_h} + ruler {ruler_h}px)")

    # Grid lines should be at correct positions
    results = verify_grid_lines_on_canvas(grid_img, 0, 0, ruler_h, major_spacing, content_w, content_h)
    failures = [r for r in results if not r["pass"]]
    print(f"  Grid lines checked: {len(results)}, failures: {len(failures)}")
    for f_item in failures:
        print(f"    FAIL: {f_item}")

    # Ruler labels should exist
    ruler_info = verify_ruler_labels(grid_img, 0, 0, ruler_h, major_spacing, content_w, content_h)
    print(f"  Ruler labels: top={ruler_info['top_has_labels']}, left={ruler_info['left_has_labels']}")

    # Targets should be visible in content area
    for tx, ty, label in targets:
        canvas_x = ruler_h + tx
        canvas_y = ruler_h + ty
        pixel = grid_img.getpixel((canvas_x, canvas_y))
        print(f"  Target {label} at abs({tx},{ty}) -> canvas({canvas_x},{canvas_y}): pixel={pixel}")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = len(failures) == 0 and ruler_info['top_has_labels'] and ruler_info['left_has_labels']
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_cropped_window():
    """Test: cropped to window region. Grid labels show absolute coords."""
    print("=" * 60)
    print("TEST: Cropped window region")
    print("=" * 60)

    full_w, full_h = 1920, 1080
    full_img = make_test_image(full_w, full_h, [
        (500, 400, "InWindow"),
    ])

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        full_img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")

    wx, wy, ww, wh = 300, 200, 800, 600
    padding = 50
    crop_region = (wx - padding, wy - padding, ww + 2 * padding, wh + 2 * padding)

    add_grid_overlay(input_path, output_path, crop_region=crop_region)

    grid_img = Image.open(output_path)
    origin_x = wx - padding  # 250
    origin_y = wy - padding  # 150
    crop_w = ww + 2 * padding   # 900
    crop_h = wh + 2 * padding   # 700

    params = _compute_grid_params(crop_w, crop_h)
    ruler_h = params["ruler_height"]
    major_spacing = params["major_spacing"]

    expected_canvas_w = ruler_h + crop_w
    expected_canvas_h = ruler_h + crop_h
    print(f"  Canvas size: {grid_img.size} expected ({expected_canvas_w},{expected_canvas_h})")

    # Target at abs(500, 400) -> content img(250, 250) -> canvas(ruler_h+250, ruler_h+250)
    target_canvas_x = ruler_h + (500 - origin_x)
    target_canvas_y = ruler_h + (400 - origin_y)
    pixel = grid_img.getpixel((target_canvas_x, target_canvas_y))
    print(f"  Target at abs(500,400) -> canvas({target_canvas_x},{target_canvas_y}): pixel={pixel}")

    # Grid lines should be at correct positions
    results = verify_grid_lines_on_canvas(grid_img, origin_x, origin_y, ruler_h, major_spacing, crop_w, crop_h)
    failures = [r for r in results if not r["pass"]]
    print(f"  Grid lines checked: {len(results)}, failures: {len(failures)}")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = len(failures) == 0
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_dual_monitor():
    """Test: dual monitor (4480x1440). Verify adaptive scaling kicks in."""
    print("=" * 60)
    print("TEST: Dual monitor (4480x1440)")
    print("=" * 60)

    content_w, content_h = 4480, 1440
    targets = [
        (1280, 720, "Mon1-Center"),
        (3520, 540, "Mon2-Center"),
    ]

    img = make_test_image(content_w, content_h, targets)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")
    add_grid_overlay(input_path, output_path)

    grid_img = Image.open(output_path)
    params = _compute_grid_params(content_w, content_h)
    ruler_h = params["ruler_height"]
    major_spacing = params["major_spacing"]

    print(f"  Canvas size: {grid_img.size}")
    print(f"  Adaptive params: spacing={major_spacing}px, font={params['font_size']}px")
    print(f"  Vision scale: {params['vision_scale']:.3f}")
    print(f"  Cell in vision: {major_spacing * params['vision_scale']:.0f}px")

    # Verify grid lines
    results = verify_grid_lines_on_canvas(grid_img, 0, 0, ruler_h, major_spacing, content_w, content_h)
    failures = [r for r in results if not r["pass"]]
    print(f"  Grid lines checked: {len(results)}, failures: {len(failures)}")

    # Count ruler labels (should be MUCH fewer than old 616 intersection labels)
    n_x_labels = content_w // major_spacing
    n_y_labels = content_h // major_spacing
    total_labels = n_x_labels + n_y_labels
    print(f"  Ruler labels: {n_x_labels} top + {n_y_labels} left = {total_labels} total")
    print(f"  (Old method would have {n_x_labels * n_y_labels} intersection labels)")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = len(failures) == 0
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_dual_monitor_cropped():
    """Test: dual monitor, cropped to a window on monitor 2."""
    print("=" * 60)
    print("TEST: Dual monitor, cropped to window on monitor 2")
    print("=" * 60)

    img = make_test_image(4480, 1440, [(3200, 400, "Target")])

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")

    wx, wy, ww, wh = 2800, 200, 800, 600
    padding = 50
    crop_region = (wx - padding, wy - padding, ww + 2 * padding, wh + 2 * padding)

    add_grid_overlay(input_path, output_path, crop_region=crop_region)

    grid_img = Image.open(output_path)
    origin_x = wx - padding  # 2750
    origin_y = wy - padding  # 150
    crop_w = ww + 2 * padding
    crop_h = wh + 2 * padding

    params = _compute_grid_params(crop_w, crop_h)
    ruler_h = params["ruler_height"]
    major_spacing = params["major_spacing"]

    print(f"  Origin: ({origin_x}, {origin_y})")
    print(f"  Canvas size: {grid_img.size}")

    # Target at abs(3200, 400) -> canvas(ruler_h + 450, ruler_h + 250)
    target_cx = ruler_h + (3200 - origin_x)
    target_cy = ruler_h + (400 - origin_y)
    pixel = grid_img.getpixel((target_cx, target_cy))
    print(f"  Target at abs(3200,400) -> canvas({target_cx},{target_cy}): {pixel}")

    results = verify_grid_lines_on_canvas(grid_img, origin_x, origin_y, ruler_h, major_spacing, crop_w, crop_h)
    failures = [r for r in results if not r["pass"]]
    print(f"  Grid lines checked: {len(results)}, failures: {len(failures)}")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = len(failures) == 0
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_mouse_position():
    """Test: mouse crosshair drawn at correct canvas position."""
    print("=" * 60)
    print("TEST: Mouse position crosshair accuracy")
    print("=" * 60)

    content_w, content_h = 800, 600
    img = make_test_image(content_w, content_h)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")

    mouse_abs = (350, 275)
    add_grid_overlay(input_path, output_path, mouse_pos=mouse_abs)

    grid_img = Image.open(output_path)
    params = _compute_grid_params(content_w, content_h)
    ruler_h = params["ruler_height"]

    # Mouse at abs(350, 275) -> canvas(ruler_h+350, ruler_h+275)
    canvas_mx = ruler_h + mouse_abs[0]
    canvas_my = ruler_h + mouse_abs[1]
    pixel = grid_img.getpixel((canvas_mx, canvas_my))
    g = pixel[1]
    is_green = g > 200
    print(f"  Mouse at abs{mouse_abs} -> canvas({canvas_mx},{canvas_my}): pixel={pixel}, green={is_green}")

    # Verify ruler highlights (green lines in ruler area pointing to mouse)
    # Check top ruler at mouse's x position
    top_pixel = grid_img.getpixel((canvas_mx, ruler_h // 2))
    top_green = top_pixel[1] > 200
    print(f"  Top ruler highlight at x={canvas_mx}: pixel={top_pixel}, green={top_green}")

    # Check left ruler at mouse's y position
    left_pixel = grid_img.getpixel((ruler_h // 2, canvas_my))
    left_green = left_pixel[1] > 200
    print(f"  Left ruler highlight at y={canvas_my}: pixel={left_pixel}, green={left_green}")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = is_green
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_mouse_position_cropped():
    """Test: mouse crosshair in cropped image uses absolute coords correctly."""
    print("=" * 60)
    print("TEST: Mouse position in cropped image")
    print("=" * 60)

    img = make_test_image(1920, 1080)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")

    crop_region = (350, 250, 700, 500)
    mouse_abs = (600, 500)

    add_grid_overlay(input_path, output_path, mouse_pos=mouse_abs, crop_region=crop_region)

    grid_img = Image.open(output_path)
    origin_x, origin_y = 350, 250
    params = _compute_grid_params(700, 500)
    ruler_h = params["ruler_height"]

    # Mouse at abs(600,500) -> content(250,250) -> canvas(ruler_h+250, ruler_h+250)
    canvas_mx = ruler_h + (mouse_abs[0] - origin_x)
    canvas_my = ruler_h + (mouse_abs[1] - origin_y)

    pixel = grid_img.getpixel((canvas_mx, canvas_my))
    g = pixel[1]
    is_green = g > 200
    print(f"  Mouse abs{mouse_abs} -> canvas({canvas_mx},{canvas_my}): pixel={pixel}, green={is_green}")

    Path(input_path).unlink()
    Path(output_path).unlink()

    passed = is_green
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def test_label_readability():
    """Test: verify grid labels are readable at different sizes (ruler approach)."""
    print("=" * 60)
    print("TEST: Label readability analysis (ruler approach)")
    print("=" * 60)

    sizes = [
        (800, 600, "Small window"),
        (1920, 1080, "HD monitor"),
        (2560, 1440, "QHD monitor"),
        (4480, 1440, "Dual QHD+HD"),
        (3840, 2160, "4K monitor"),
    ]

    for w, h, desc in sizes:
        p = _compute_grid_params(w, h)
        vs = p["vision_scale"]
        ms = p["major_spacing"]

        # With rulers, total labels = horizontal + vertical (not product)
        n_x = w // ms
        n_y = h // ms
        total_labels = n_x + n_y
        old_labels = n_x * n_y

        # Canvas is slightly larger due to rulers
        canvas_w = p["ruler_height"] + w
        canvas_h = p["ruler_height"] + h
        canvas_vs = min(1.0, 1568 / max(canvas_w, canvas_h))
        label_vis = p["font_size"] * canvas_vs

        print(f"  {desc} ({w}x{h}):")
        print(f"    Ruler labels: {total_labels} (was {old_labels} intersection labels)")
        print(f"    Font: {p['font_size']}px, in vision: {label_vis:.1f}px")
        print(f"    Grid spacing: {ms}px, cell in vision: {ms * canvas_vs:.0f}px")
        print(f"    Readable: {'YES' if label_vis >= 6 else 'NO'}")

    print(f"  RESULT: INFORMATIONAL")
    return True


def test_no_intersection_labels():
    """Test: verify the new overlay does NOT place labels at every intersection."""
    print("=" * 60)
    print("TEST: No intersection labels (only ruler labels)")
    print("=" * 60)

    content_w, content_h = 800, 600
    img = make_test_image(content_w, content_h)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        input_path = f.name
        img.save(input_path)

    output_path = input_path.replace(".png", "_grid.png")
    add_grid_overlay(input_path, output_path)

    grid_img = Image.open(output_path)
    params = _compute_grid_params(content_w, content_h)
    ruler_h = params["ruler_height"]
    major_spacing = params["major_spacing"]

    # Check a grid intersection point in the content area for yellow text
    # (there should be NO yellow labels inside the content area)
    yellow_in_content = 0
    def first_grid_pos(origin, spacing):
        pos = (origin // spacing) * spacing
        if pos < origin:
            pos += spacing
        return pos

    start_x = first_grid_pos(0, major_spacing)
    start_y = first_grid_pos(0, major_spacing)

    for abs_x in range(start_x, content_w, major_spacing):
        for abs_y in range(start_y, content_h, major_spacing):
            canvas_x = ruler_h + abs_x
            canvas_y = ruler_h + abs_y
            # Check a small region around the intersection for yellow text
            for dx in range(2, 20):
                for dy in range(2, 20):
                    px = canvas_x + dx
                    py = canvas_y + dy
                    if px < grid_img.size[0] and py < grid_img.size[1]:
                        pixel = grid_img.getpixel((px, py))
                        r, g, b = pixel[0], pixel[1], pixel[2]
                        if r > 200 and g > 200 and b < 100:  # Yellow
                            yellow_in_content += 1

    print(f"  Yellow pixels in content intersection areas: {yellow_in_content}")
    passed = yellow_in_content == 0
    print(f"  RESULT: {'PASS' if passed else 'FAIL'} (expected 0 - labels only in rulers)")

    Path(input_path).unlink()
    Path(output_path).unlink()

    return passed


def main():
    print("Grid Overlay Coordinate Accuracy Tests")
    print("=" * 60)
    print()

    results = {}

    results["adaptive_params"] = test_adaptive_params()
    print()
    results["basic_fullscreen"] = test_basic_fullscreen()
    print()
    results["cropped_window"] = test_cropped_window()
    print()
    results["dual_monitor"] = test_dual_monitor()
    print()
    results["dual_monitor_cropped"] = test_dual_monitor_cropped()
    print()
    results["mouse_position"] = test_mouse_position()
    print()
    results["mouse_cropped"] = test_mouse_position_cropped()
    print()
    results["no_intersection_labels"] = test_no_intersection_labels()
    print()
    results["label_readability"] = test_label_readability()
    print()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    all_pass = all(results.values())
    print()
    print(f"Overall: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
