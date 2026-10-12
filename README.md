# x11-ocr

Drive the Linux desktop by looking at it: a frame grab goes through local
RapidOCR, comes back as a `blocks -> lines -> words` element tree with pixel
bboxes, and you click the text you found. No coordinate guessing from
thumbnails; line boxes are pixel-exact, word boxes are within a few px.

Works on Plasma Wayland and X11. Also usable as a Claude Code skill (a
`SKILL.md`-style workflow is in the examples below).

## Install

```sh
pip install .
```

Dependencies: `rapidocr-onnxruntime` (OCR, CPU), `Pillow`, `numpy`.

Also needs, from the distro:

- a screen capture tool: `spectacle` (KDE) or ImageMagick `import`
- `xdotool`
- AT-SPI bindings: `apt install gir1.2-atspi-2.0 python3-gi` (Debian/Ubuntu;
  equivalent on other distros). On plain X11 sessions these are usually
  already present.

Display/auth: the scripts resolve `DISPLAY` (env or `/tmp/.X11-unix`) and
`XAUTHORITY` (env or `/run/user/<uid>/xauth_*`) themselves. Apps you launch
for testing need the full session env:

```sh
setsid env DISPLAY=:0 XAUTHORITY=$(ls -1 /run/user/1000/xauth_* | head -1) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus kdialog --msgbox test &
```

## Quickstart

```sh
x11-windows                        # real window list (AT-SPI), both X11 and Wayland windows
x11-screen-elements                # whole desktop element tree, JSON on stdout
x11-screen-elements Settings       # only lines containing "Settings"
x11-screen-elements --window code  # OCR one window only (faster, denser)
x11-click-text OK --window kdialog # OCR fresh, click the matched text
x11-click-text "Open" --dry-run    # report the coords, do not click
```

Output of the element tools is JSON. `frame.path` points at the captured PNG
(`/tmp/x11-ocr/frame.png`), so you can view the image next to the tree, and
`frame.sha12` changes on every grab, which makes "verify after acting"
measurable:

```json
{"ok": true,
 "frame": {"w": 4480, "h": 1843, "path": "/tmp/x11-ocr/frame.png", "sha12": "…", "tiles": 12},
 "blocks": [{"id": "b0", "lines": [{"id": "b0l0", "text": "Settings",
             "score": 0.93, "bbox": [2336, 425, 62, 21]}]}]}
```

The click tool's result adds the match (`level`, `text`, `bbox`, `center`,
score), the computed `x`/`y`, and which `click_method` delivered the click.

## How it works

1. `framegrab.grab_frame` captures the full desktop with spectacle
   (`spectacle -b -f -n -o`), falling back to ImageMagick `import`. This
   captures all monitors plus visible menus/popups, and keeps bbox space
   equal to screen space.
2. `x11_ocr.vision` (RapidOCR wrapper) reads the frame into
   blocks/lines/words(/letters). Word and letter boxes are estimated by
   proportional character-width accumulation along the line box, so they are
   close but not exact; click on word centers, not letter boxes.
3. `framegrab.ocr_frame` tiles the frame at native resolution (1280x720 with
   64 px overlap, deduplicated after merge) because RapidOCR's det model caps
   its longest side at 1280: on a 4480x1843 dual-monitor composite the
   whole-frame pass was measured at ~0.29x downscale where small dialog text
   vanishes, while tiling keeps text at 1:1 density.

Measured on that dual-monitor desktop, i7, CPU only: a single 300x120 window
crop OCRs in ~0.7 s and the full 12-tile desktop takes ~5 s. Prefer
`--window` when you know the target.

## Click delivery, and why there are two mechanisms

Verified on a Plasma 6 Wayland session (`kwin_wayland` + rootless Xwayland),
2026-10-12:

| Mechanism | X11 / Xwayland windows | Wayland-native windows |
|---|---|---|
| Find window + geometry via AT-SPI (`x11-windows`) | works | works |
| `wmctrl -l`, `xdotool search` | work | do not see these windows |
| `xdotool key Return/...` (focused window) | works | untested |
| `xdotool` button clicks | **not delivered** (verified: click runs, app never sees it) | not delivered |
| AT-SPI `do_action` press (`click_text.py --method atspi`) | works | works |

So the default (`auto`) sends an AT-SPI press when an actionable node sits
under the matched text (buttons, menu items, links; left click only), and
falls back to plain xdotool mouse events otherwise. Non-default buttons and
multi-clicks always use xdotool, and on Wayland those are the clicks that may
not land; check `click_method` in the result and re-verify the state change
afterward.

Keyboard recipes (after activating your own target; keys land in whatever is
focused):

```sh
WIN=$(xdotool search --name 'MyApp' | head -1)
xdotool windowactivate --sync $WIN
xdotool type "192.168.1.100"; xdotool key Return
xdotool key Escape; xdotool key Tab
```

Never send keys while another window (the user's terminal) has focus.

## extras/

- `list_controls.py "AppName"`: the app's own AT-SPI actionable controls
  (role, name, coords, actions; `--tree` for the full hierarchy). Use when
  OCR cannot see what you need (icon-only toolbars, canvases). Note AT-SPI
  window geometry can report (0,0) for some large Wayland windows; check the
  rect against the frame image before cropping.
- `check_popups.py "AppName"`: popup/dialog liveness (exit 0 none, 1 found).
- `grid_overlay.py /tmp/frame.png`: draws a labeled coordinate grid onto the
  screenshot for icon-only, OCR-hostile UI. Last resort.

## Troubleshooting

- `no gi bindings here and /usr/bin/python3 fallback also lacks them`:
  install the AT-SPI bindings (`gir1.2-atspi-2.0 python3-gi`).
- `cannot import x11_ocr.vision`: the calling interpreter lacks
  numpy/Pillow/rapidocr; use a python where the package is installed.
- Capture fails: spectacle is primary, `import -window root` is the fallback.
- Frame looks stale: each grab rewrites `frame.png`; compare `frame.sha12`
  between the action and the follow-up read.
- A freshly launched test window reports geometry but never renders
  (verified once on Plasma 6 Wayland): KWin can leave a self-placed window
  outside the composited root (its x exceeds the root width) and never draw
  it, and AT-SPI may stop listing it too; no window rules or scripts were
  involved, and the same code worked earlier the same day. Trust the frame
  over reported geometry, activate your target first (`wmctrl -i -a ID`),
  and prefer `--dry-run` verification.
- On headless servers rapidocr may pull GUI OpenCV; `opencv-python-headless`
  can be installed alongside to keep the desktop libs off the machine.

## Provenance and license

`vision.py` is vendored from
[glkvm-mcp](https://github.com/GlassOnTin/glkvm-mcp), the same OCR pipeline
driving a GL.iNet GLKVM KVM-over-IP target. Everything here is
AGPL-3.0-or-later (see `LICENSE`).