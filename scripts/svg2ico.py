#!/usr/bin/env python3
"""Convert SVG to ICO and PNG icon files.

This script takes an SVG file and generates:
- PNG files at standard icon sizes (16, 32, 64, 128, 256)
- An ICO file combining the smaller sizes (16, 32, 64)

Usage:
    python -m scripts.svg2ico <svg_file>
"""

import argparse
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

try:
    import cairosvg
except ImportError:
    print("Error: cairosvg is required. Install with: uv pip install cairosvg")
    sys.exit(1)

# Standard icon sizes in pixels
ICON_SIZES = (16, 32, 64, 128, 256)
ICO_SIZES = (16, 32, 64)  # Supported sizes for ICO format


def svg_to_png(svg_path: Path, size: int) -> Image.Image:
    """Convert SVG to PNG at a specific size.

    Args:
        svg_path: Path to the SVG file.
        size: Target image size (width and height in pixels).

    Returns:
        A PIL Image object in RGBA mode.
    """
    png_bytes = cairosvg.svg2png(
        url=str(svg_path),
        output_width=size,
        output_height=size,
    )
    return Image.open(BytesIO(png_bytes)).convert("RGBA")


def generate_icons(svg_path: Path, output_dir: Path) -> None:
    """Generate PNG and ICO files from SVG.

    Args:
        svg_path: Path to the SVG file.
        output_dir: Directory where icons will be saved.

    Returns:
        None.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting {svg_path.name}...")

    # Generate PNG files at all sizes
    png_images: dict[int, Image.Image] = {}
    for size in ICON_SIZES:
        print(f"  Generating {size}x{size} PNG...")
        img = svg_to_png(svg_path, size)
        png_path = output_dir / f"icon_{size}.png"
        img.save(png_path, "PNG")
        png_images[size] = img
        print(f"    Saved {png_path}")

    # Generate ICO file from smaller sizes
    print("  Generating ICO file...")
    ico_images = [png_images[size] for size in ICO_SIZES]
    ico_path = output_dir / "icon.ico"
    ico_images[0].save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"    Saved {ico_path}")

    print("Done!")


def main() -> None:
    """Parse arguments and generate icons."""
    parser = argparse.ArgumentParser(
        prog="svg2ico",
        description="Convert SVG to ICO and PNG icon files.",
    )
    parser.add_argument(
        "svg_file",
        type=Path,
        help="Path to the SVG file to convert.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: icons/).",
    )

    args = parser.parse_args()
    svg_path = args.svg_file

    # Validate SVG file
    if not svg_path.exists():
        print(f"Error: SVG file not found: {svg_path}", file=sys.stderr)
        sys.exit(1)

    if svg_path.suffix.lower() != ".svg":
        print(f"Error: File must be an SVG: {svg_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output directory
    if args.output:
        output_dir = args.output
    else:
        # Relative to project root (two levels up from scripts/)
        output_dir = svg_path.parent.parent / "icons"

    try:
        generate_icons(svg_path, output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
