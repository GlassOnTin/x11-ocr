"""x11-ocr: drive the Linux desktop by OCR.

RapidOCR turns a screen frame into a blocks/lines/words element tree with
pixel-true bboxes; clicking targets the text you found, never guessed
coordinates. AT-SPI presses deliver the click (works on Plasma Wayland and
X11). AGPL-3.0-or-later; vision.py is vendored from glkvm-mcp.
"""

__version__ = "0.1.0"