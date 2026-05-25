"""ffmpeg + pillow-heif Live Photo format conversion."""

import asyncio
import uuid
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()


async def make_livephoto(video_path: str | Path, output_dir: str | Path) -> tuple[Path, Path]:
    """Convert video to Live Photo pair (MOV + HEIC).

    Returns (mov_path, heic_path).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content_id = str(uuid.uuid4()).upper()
    base_name = output_dir / content_id[:8]

    mov_path = base_name.with_suffix(".MOV")
    heic_path = base_name.with_suffix(".HEIC")

    # Step 1: Convert video to MOV with QuickTime metadata
    await _convert_to_mov(str(video_path), str(mov_path), content_id)

    # Step 2: Extract first frame as HEIC with matching content ID
    png_path = output_dir / "frame.png"
    await _extract_frame(str(video_path), str(png_path))
    _png_to_heic(str(png_path), str(heic_path), content_id)
    png_path.unlink(missing_ok=True)

    return mov_path, heic_path


async def _convert_to_mov(input_path: str, output_path: str, content_id: str) -> None:
    """ffmpeg: video -> MOV (H.264) with QuickTime metadata."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
        "-metadata", f"com.apple.quicktime.content.identifier={content_id}",
        "-metadata", "com.apple.quicktime.still-image-time=0",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg MOV conversion failed: {stderr.decode()}")


async def _extract_frame(video_path: str, output_path: str) -> None:
    """ffmpeg: extract first frame as PNG."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "select=eq(n\\,0)",
        "-vframes", "1",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {stderr.decode()}")


def _png_to_heic(png_path: str, heic_path: str, content_id: str) -> None:
    """PNG -> HEIC via pillow-heif.
    Note: pillow-heif cannot write QuickTime content_identifier directly.
    TODO: post-process with exiftool or binary atom injection if iOS pairing fails.
    """
    img = Image.open(png_path)
    heif_file = pillow_heif.HeifFile()
    heif_file.add_from_pillow(img)
    heif_file.save(heic_path, quality=85)
