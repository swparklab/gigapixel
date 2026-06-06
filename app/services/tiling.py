from __future__ import annotations


def estimate_canvas_memory_bytes(width: int, height: int, channels: int = 3, bytes_per_channel: int = 1) -> int:
    return int(width) * int(height) * int(channels) * int(bytes_per_channel)


def assert_canvas_size(width: int, height: int, max_pixels: int) -> None:
    pixels = int(width) * int(height)
    if pixels > int(max_pixels):
        raise RuntimeError(f"Stitched canvas size ({pixels} pixels) exceeds configured limit ({max_pixels} pixels).")
