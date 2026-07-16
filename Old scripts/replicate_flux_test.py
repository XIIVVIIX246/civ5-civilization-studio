from pathlib import Path
import os
import replicate
from PIL import Image

OUT = Path("replicate_test_output.png")

if not os.environ.get("REPLICATE_API_TOKEN"):
    raise RuntimeError("REPLICATE_API_TOKEN is not set.")

prompt = (
    "Create a Civilization V: Brave New World custom civilization icon in painterly "
    "historical realism. A bronze ancient sun emblem centered on a dark green background. "
    "Strong readable silhouette, high contrast, square icon composition, no text, "
    "no border, no watermark."
)

output = replicate.run(
    "black-forest-labs/flux-schnell",
    input={
        "prompt": prompt,
        "output_format": "png"
    }
)

first = output[0] if isinstance(output, list) else output

with open(OUT, "wb") as f:
    if hasattr(first, "read"):
        f.write(first.read())
    elif isinstance(first, bytes):
        f.write(first)
    else:
        import urllib.request
        urllib.request.urlretrieve(str(first), OUT)

# Verify Pillow can read it.
img = Image.open(OUT)
print(f"Generated: {OUT.resolve()}")
print(f"Image size: {img.size}")
print(f"Image mode: {img.mode}")