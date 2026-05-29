"""ffmpeg + pillow-heif Live Photo format conversion."""

import asyncio
import shutil
import uuid
from pathlib import Path

import pillow_heif
from PIL import Image

try:
    from makelive import make_live_photo as _makelive_make
    from makelive import save_live_photo_pair_as_pvt as _makelive_save_pvt

    _HAS_MAKELIVE = True
except ImportError:
    _HAS_MAKELIVE = False

pillow_heif.register_heif_opener()

_FFMPEG = "ffmpeg"


def set_ffmpeg_path(path: str) -> None:
    global _FFMPEG
    _FFMPEG = path


async def make_livephoto(video_path: str | Path, output_dir: str | Path) -> tuple[Path, Path, Path]:
    """Convert video to Live Photo pair (MOV + HEIC) + .pvt package.

    Returns (mov_path, heic_path, pvt_path). On macOS, ContentIdentifier is
    injected into both files for iOS auto-pairing. On Windows, files are
    produced without ContentIdentifier — transfer to a Mac for final pairing.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content_id = str(uuid.uuid4()).upper()
    base_name = output_dir / content_id[:8]

    mov_path = base_name.with_suffix(".MOV")
    heic_path = base_name.with_suffix(".HEIC")

    # Step 1: Convert video to MOV with ffmpeg
    await _convert_to_mov(str(video_path), str(mov_path))

    # Step 2: Extract first frame as PNG, then convert to HEIC
    png_path = output_dir / "frame.png"
    await _extract_frame(str(video_path), str(png_path))
    _png_to_heic(str(png_path), str(heic_path))
    png_path.unlink(missing_ok=True)

    # Step 3: ContentIdentifier injection + .pvt package
    if _HAS_MAKELIVE:
        _makelive_make(str(heic_path), str(mov_path))
        _, pvt_path = _makelive_save_pvt(str(heic_path), str(mov_path))
    else:
        pvt_path = _make_pvt_fallback(str(heic_path), str(mov_path))
        print("[LIVEPHOTO] makelive not available — .pvt created without ContentIdentifier pairing")

    return mov_path, heic_path, Path(pvt_path)


def _make_pvt_fallback(heic_path: str, mov_path: str) -> str:
    """Create minimal .pvt package without ContentIdentifier injection.

    On Windows (where makelive/pyobjc isn't available), we create a simple
    .pvt directory containing the MOV and HEIC files. The user can transfer
    these to a Mac for final ContentIdentifier pairing.
    """
    heic = Path(heic_path)
    mov = Path(mov_path)
    pvt_dir = heic.parent / (heic.stem + ".pvt")
    pvt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mov, pvt_dir / mov.name)
    shutil.copy2(heic, pvt_dir / heic.name)
    return str(pvt_dir)


async def _convert_to_mov(input_path: str, output_path: str) -> None:
    """ffmpeg: video -> MOV (H.264)."""
    cmd = [
        _FFMPEG, "-y",
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


async def _extract_frame(video_path: str, output_path: str) -> None:
    """ffmpeg: extract first frame as PNG."""
    cmd = [
        _FFMPEG, "-y",
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
