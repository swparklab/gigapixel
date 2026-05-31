import math
import shutil
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from PIL import Image

try:
    import pyvips  # type: ignore
except Exception:  # pragma: no cover
    pyvips = None

# Pillow's decompression-bomb guard is too low for gigapixel workflows.
# We enforce our own explicit max pixel policy in this module instead.
Image.MAX_IMAGE_PIXELS = None


def _write_descriptor(descriptor_path: Path, width: int, height: int, tile_size: int, overlap: int) -> None:
    image = Element(
        "Image",
        {
            "TileSize": str(tile_size),
            "Overlap": str(overlap),
            "Format": "jpg",
            "xmlns": "http://schemas.microsoft.com/deepzoom/2008",
        },
    )
    SubElement(image, "Size", {"Width": str(width), "Height": str(height)})
    descriptor_path.write_text(tostring(image, encoding="unicode"), encoding="utf-8")


def _generate_with_pillow(
    stitched_image_path: Path,
    output_base: Path,
    tile_size: int,
    overlap: int,
    max_source_pixels: int,
) -> tuple[Path, int, int]:
    descriptor_path = output_base.with_suffix(".dzi")
    tiles_root = output_base.parent / f"{output_base.name}_files"

    if tiles_root.exists():
        shutil.rmtree(tiles_root)
    tiles_root.mkdir(parents=True, exist_ok=True)

    with Image.open(stitched_image_path) as source:
        width, height = source.size
        pixel_count = width * height
        if pixel_count > max_source_pixels:
            raise RuntimeError(
                f"Image size ({pixel_count} pixels) exceeds configured limit ({max_source_pixels} pixels)."
            )
        source = source.convert("RGB")
        max_level = int(math.ceil(math.log2(max(width, height))))

        for level in range(max_level + 1):
            divisor = 2 ** (max_level - level)
            level_width = max(1, int(math.ceil(width / divisor)))
            level_height = max(1, int(math.ceil(height / divisor)))
            level_img = source.resize((level_width, level_height), Image.Resampling.LANCZOS)

            level_dir = tiles_root / str(level)
            level_dir.mkdir(parents=True, exist_ok=True)

            cols = int(math.ceil(level_width / tile_size))
            rows = int(math.ceil(level_height / tile_size))

            for row in range(rows):
                for col in range(cols):
                    left = max(col * tile_size - (overlap if col > 0 else 0), 0)
                    top = max(row * tile_size - (overlap if row > 0 else 0), 0)
                    right = min((col + 1) * tile_size + (overlap if col < cols - 1 else 0), level_width)
                    bottom = min((row + 1) * tile_size + (overlap if row < rows - 1 else 0), level_height)

                    tile = level_img.crop((left, top, right, bottom))
                    tile.save(level_dir / f"{col}_{row}.jpg", format="JPEG", quality=90)

    _write_descriptor(descriptor_path, width, height, tile_size, overlap)
    return descriptor_path, width, height


def generate_dzi(
    stitched_image_path: Path,
    dzi_output_dir: Path,
    tile_size: int = 256,
    overlap: int = 1,
    max_source_pixels: int = 10_000_000_000,
) -> tuple[Path, int, int]:
    dzi_output_dir.mkdir(parents=True, exist_ok=True)
    output_base = dzi_output_dir / "image"

    descriptor = output_base.with_suffix(".dzi")
    tiles_root = dzi_output_dir / "image_files"

    if descriptor.exists():
        descriptor.unlink()
    if tiles_root.exists():
        shutil.rmtree(tiles_root)

    if pyvips is not None:
        image = pyvips.Image.new_from_file(str(stitched_image_path), access="sequential")
        pixel_count = int(image.width) * int(image.height)
        if pixel_count > max_source_pixels:
            raise RuntimeError(
                f"Image size ({pixel_count} pixels) exceeds configured limit ({max_source_pixels} pixels)."
            )
        image.dzsave(
            str(output_base),
            layout="dz",
            tile_size=tile_size,
            overlap=overlap,
            suffix=".jpg[Q=90]",
        )
        return descriptor, int(image.width), int(image.height)

    return _generate_with_pillow(
        stitched_image_path,
        output_base,
        tile_size,
        overlap,
        max_source_pixels=max_source_pixels,
    )
