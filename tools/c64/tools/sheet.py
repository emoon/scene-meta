#!/usr/bin/env python3
"""Contact sheet of screenshots: tools/sheet.py out.jpg a.png b.png ..."""
import sys

from PIL import Image, ImageDraw

out, files = sys.argv[1], sys.argv[2:]
cols, w, h = 6, 256, 180
sheet = Image.new("RGB", (cols * w, ((len(files) + cols - 1) // cols) * h))
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB").resize((w, h))
    ImageDraw.Draw(im).text((4, 4), f.rsplit("/", 1)[-1], fill=(255, 255, 0))
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(out, quality=80)
