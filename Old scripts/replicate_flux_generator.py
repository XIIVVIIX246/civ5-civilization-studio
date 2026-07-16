"""
replicate_flux_generator.py

Standalone Replicate FLUX Schnell image generation helper for the Civ V PNG-to-DDS pipeline.

This module does not convert DDS files and does not modify the existing converter.
It performs one task: one text prompt -> one normalized PNG file.

------------------------------------------------------------------------------
Install:
  python -m pip install replicate Pillow

Set token for current PowerShell session only:
  $env:REPLICATE_API_TOKEN="your_token_here"

Set token permanently (Windows user environment variable):
  setx REPLICATE_API_TOKEN "your_token_here"
  Then close and reopen PowerShell.

Run:
  python replicate_flux_generator.py --prompt "..." --out test.png
------------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import io
import os
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

try:
    import replicate
except ImportError:  # Defer the error until generation is actually attempted.
    replicate = None

MODEL_DEFAULT = "black-forest-labs/flux-schnell"

_TOKEN_ENV_VAR = "REPLICATE_API_TOKEN"


def check_replicate_token() -> None:
    """Raise RuntimeError if REPLICATE_API_TOKEN is missing or blank.

    Reads the token from the environment only. Never prints or returns it.
    """
    token = os.environ.get(_TOKEN_ENV_VAR)
    if not token or not token.strip():
        raise RuntimeError(
            f"{_TOKEN_ENV_VAR} is not set. "
            "Set it before using Replicate image generation."
        )


def build_flux_input(
    prompt: str,
    output_format: str = "png",
    width: int | None = None,
    height: int | None = None,
    num_outputs: int | None = None,
    num_inference_steps: int | None = None,
    go_fast: bool | None = None,
    output_quality: int | None = None,
) -> dict:
    """Build a Replicate input dictionary for FLUX Schnell.

    Only includes optional keys when they are explicitly provided (not None),
    because Replicate model schemas can change and may reject unknown/extra keys.
    """
    if not prompt or not prompt.strip():
        raise ValueError("A non-empty prompt is required.")

    flux_input: dict[str, Any] = {"prompt": prompt}

    # output_format is included whenever it is a non-blank string.
    if output_format is not None and str(output_format).strip():
        flux_input["output_format"] = output_format

    if width is not None:
        flux_input["width"] = width
    if height is not None:
        flux_input["height"] = height
    if num_outputs is not None:
        flux_input["num_outputs"] = num_outputs
    if num_inference_steps is not None:
        flux_input["num_inference_steps"] = num_inference_steps
    if go_fast is not None:
        flux_input["go_fast"] = go_fast
    if output_quality is not None:
        flux_input["output_quality"] = output_quality

    return flux_input


def _resolve_first_output(output_obj: Any) -> Any:
    """If the Replicate output is a list, return its first element.

    Raises RuntimeError on an empty list.
    """
    if isinstance(output_obj, list):
        if not output_obj:
            raise RuntimeError("Replicate returned an empty list.")
        return output_obj[0]
    return output_obj


def _read_bytes_from_output(obj: Any) -> bytes:
    """Normalize a single Replicate output item into raw image bytes.

    Handles:
      - file-like object with .read()
      - bytes / bytearray
      - URL string (http:// or https://)
      - local path string or pathlib.Path
    """
    # File-like object (Replicate FileOutput supports .read()).
    if hasattr(obj, "read"):
        data = obj.read()
        if not data:
            raise RuntimeError(
                "Replicate returned a file-like object but it contained no data."
            )
        return data

    # Raw bytes.
    if isinstance(obj, (bytes, bytearray)):
        if not obj:
            raise RuntimeError("Replicate returned empty bytes.")
        return bytes(obj)

    # URL string.
    if isinstance(obj, str) and obj.startswith(("http://", "https://")):
        with urllib.request.urlopen(obj) as response:  # noqa: S310 (trusted Replicate URL)
            data = response.read()
        if not data:
            raise RuntimeError(f"Downloaded URL returned no data: {obj}")
        return data

    # Local path (string or Path).
    if isinstance(obj, (str, Path)):
        path = Path(obj)
        if path.exists():
            data = path.read_bytes()
            if not data:
                raise RuntimeError(f"Local output file was empty: {path}")
            return data
        raise RuntimeError(
            f"Replicate returned a path-like value that does not exist: {obj}"
        )

    raise RuntimeError(f"Unsupported Replicate output type: {type(obj).__name__}")


def save_replicate_output_as_png(output_obj: Any, output_path: Path) -> Path:
    """Save a Replicate output object as a normalized PNG.

    Handles file-like objects, URL strings, bytes, local paths, and lists
    containing any of those. The final file is always saved as PNG, even if
    Replicate returned WebP. Alpha is preserved when present.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    first = _resolve_first_output(output_obj)
    data = _read_bytes_from_output(first)

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - surface a friendly message.
        raise RuntimeError(
            "Replicate returned an output, but Pillow could not read it as an image."
        ) from exc

    # Normalize mode. Preserve alpha if present; otherwise keep RGB.
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")

    image.save(output_path, "PNG")
    return output_path


def generate_flux_image(
    prompt: str,
    output_path: str | Path,
    model: str = MODEL_DEFAULT,
    output_format: str = "png",
    width: int | None = None,
    height: int | None = None,
    num_outputs: int | None = None,
    num_inference_steps: int | None = None,
    go_fast: bool | None = None,
    output_quality: int | None = None,
    retry_minimal_on_schema_error: bool = True,
) -> Path:
    """Generate one image with Replicate FLUX Schnell and save it as PNG.

    Returns the saved output Path.
    """
    if replicate is None:
        raise RuntimeError(
            "The replicate package is not installed. Install it with:\n"
            "python -m pip install replicate"
        )

    check_replicate_token()

    output_path = Path(output_path)

    flux_input = build_flux_input(
        prompt=prompt,
        output_format=output_format,
        width=width,
        height=height,
        num_outputs=num_outputs,
        num_inference_steps=num_inference_steps,
        go_fast=go_fast,
        output_quality=output_quality,
    )

    has_optional_keys = set(flux_input.keys()) - {"prompt"}

    try:
        output = replicate.run(model, input=flux_input)
    except Exception as exc:  # noqa: BLE001
        # Retry once with prompt-only input if optional keys may have been rejected.
        if retry_minimal_on_schema_error and has_optional_keys:
            print(
                "Optional FLUX parameters were rejected. "
                "Retrying with minimal prompt-only input."
            )
            try:
                output = replicate.run(model, input={"prompt": prompt})
            except Exception:  # noqa: BLE001 - re-raise the final failure.
                raise
        else:
            raise

    return save_replicate_output_as_png(output, output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one PNG from one prompt using Replicate FLUX Schnell. "
            "Requires the REPLICATE_API_TOKEN environment variable."
        )
    )
    parser.add_argument("--prompt", required=True, help="Text prompt for image generation.")
    parser.add_argument("--out", required=True, help="Output PNG path.")
    parser.add_argument("--model", default=MODEL_DEFAULT, help="Replicate model identifier.")
    parser.add_argument("--width", type=int, default=None, help="Optional output width.")
    parser.add_argument("--height", type=int, default=None, help="Optional output height.")
    parser.add_argument("--num-outputs", type=int, default=None, dest="num_outputs")
    parser.add_argument(
        "--num-inference-steps", type=int, default=None, dest="num_inference_steps"
    )
    parser.add_argument("--go-fast", action="store_true", default=None, dest="go_fast")
    parser.add_argument("--output-format", default="png", dest="output_format")
    parser.add_argument("--output-quality", type=int, default=None, dest="output_quality")
    parser.add_argument(
        "--no-minimal-retry",
        action="store_false",
        dest="retry_minimal_on_schema_error",
        default=True,
        help="Disable the prompt-only retry on schema/input errors.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        saved = generate_flux_image(
            prompt=args.prompt,
            output_path=args.out,
            model=args.model,
            output_format=args.output_format,
            width=args.width,
            height=args.height,
            num_outputs=args.num_outputs,
            num_inference_steps=args.num_inference_steps,
            go_fast=args.go_fast,
            output_quality=args.output_quality,
            retry_minimal_on_schema_error=args.retry_minimal_on_schema_error,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1

    abs_path = saved.resolve()
    print(f"Generated image: {abs_path}")

    # Basic Pillow verification (never prints the token).
    try:
        with Image.open(abs_path) as verify:
            verify.load()
            print(f"Size: {verify.width}x{verify.height}")
            print(f"Mode: {verify.mode}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Saved file could not be re-opened for verification: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())