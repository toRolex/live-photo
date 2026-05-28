"""ffmpeg + pillow-heif Live Photo format conversion."""

import asyncio
import shutil
import uuid
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()


async def make_livephoto(video_path: str | Path, output_dir: str | Path) -> tuple[Path, Path]:
    """Convert video to Live Photo pair (MOV + HEIC).

    Returns (mov_path, heic_path). Both files share matching content_identifier
    for iOS auto-pairing.
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
    _png_to_heic(str(png_path), str(heic_path))
    png_path.unlink(missing_ok=True)

    # Step 3: Inject content_identifier into HEIC via exiftool post-process
    await _inject_heic_content_id(heic_path, content_id)

    return mov_path, heic_path


async def _convert_to_mov(input_path: str, output_path: str, content_id: str) -> None:
    """ffmpeg: video -> MOV (H.264), then exiftool for QuickTime metadata."""
    # Step 1: Convert to MOV with ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
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

    # Step 2: Inject ContentIdentifier with exiftool
    if shutil.which("exiftool"):
        cmd2 = [
            "exiftool", "-api", "QuickTime", "-overwrite_original",
            f"-Keys:ContentIdentifier={content_id}",
            output_path,
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *cmd2,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr2 = await proc2.communicate()
        if proc2.returncode != 0:
            print(f"WARNING: exiftool metadata injection failed: {stderr2.decode()}")
        else:
            print(f"[META] ContentIdentifier={content_id} injected into MOV")


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


def _png_to_heic(png_path: str, heic_path: str) -> None:
    """PNG -> HEIC via pillow-heif."""
    img = Image.open(png_path)
    heif_file = pillow_heif.HeifFile()
    heif_file.add_from_pillow(img)
    heif_file.save(heic_path, quality=85)


async def _inject_heic_content_id(heic_path: str | Path, content_id: str) -> None:
    """Inject matching DocumentID into HEIC via exiftool post-process.

    iOS pairs MOV + HEIC as Live Photo when both share the same identifier:
    - MOV: com.apple.quicktime.content.identifier (written by ffmpeg)
    - HEIC: XMP-xmpMM:DocumentID (written by exiftool)
    """
    heic_path = Path(heic_path)
    if not shutil.which("exiftool"):
        print("WARNING: exiftool not found, HEIC DocumentID will not be injected")
        return

    cmd = [
        "exiftool", "-overwrite_original",
        f"-XMP-xmpMM:DocumentID={content_id}",
        str(heic_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        print(f"WARNING: exiftool failed for {heic_path}: {stderr.decode()}")
    else:
        print(f"[META] DocumentID={content_id} injected into {heic_path.name}")
