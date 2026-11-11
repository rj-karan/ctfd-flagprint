"""Script delivery example: hide each team's flag in the low bits of a cover image.

Upload this as generate.py, upload a PNG as the input file, and set the download name to image.png.
Needs Pillow, which the flagprint/generator sandbox image includes.
"""
import os

from PIL import Image

flag = os.environ["FLAG"].encode() + b"\0"
bits = [(byte >> (7 - i)) & 1 for byte in flag for i in range(8)]

image = Image.open(os.environ["INPUT"]).convert("RGB")
width, height = image.size
if len(bits) > width * height:
    raise SystemExit("The cover image is too small for the flag.")
pixels = image.load()
for index, bit in enumerate(bits):
    x, y = index % width, index // width
    r, g, b = pixels[x, y]
    pixels[x, y] = (r, g, (b & ~1) | bit)  # the flag lives in the blue channel's lowest bit, row by row
image.save(os.path.join(os.environ["OUTPUT_DIR"], os.environ["OUTPUT_NAME"] or "image.png"))
