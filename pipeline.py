"""Core orchestration: GPT -> Seedance -> ffmpeg -> ZIP."""

import base64
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from httpx import AsyncClient

from services.gpt_image import GPTImageService
from services.livephoto import make_livephoto
from services.seedance import APIMode, CLIMode
from state import StateManager, TaskStatus

OUTPUT_DIR = Path("output")
IMAGE_DIR = OUTPUT_DIR / "images"
VIDEO_DIR = OUTPUT_DIR / "videos"


def _save_image(task_id: str, prompt: str, image_bytes: bytes) -> Path:
    """Save generated image to output/images/. Returns saved file path."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prompt = "".join(c if c.isalnum() or c in " _-" else "_" for c in prompt[:30])
    filename = f"{timestamp}_{task_id[:8]}_{safe_prompt}.png"
    filepath = IMAGE_DIR / filename
    filepath.write_bytes(image_bytes)
    return filepath


async def run_image_only(
    prompt: str,
    task_id: str,
    state: StateManager,
    gpt_service: GPTImageService,
) -> None:
    """Generate image only — returns base64, sets IMAGE_READY."""
    state.update(task_id, TaskStatus.GENERATING_IMAGE, "1/2", "正在生成图片…")
    try:
        image_bytes = await gpt_service.generate(prompt)
        saved_path = _save_image(task_id, prompt, image_bytes)
        print(f"[SAVE] Image saved to {saved_path}")
        image_base64 = base64.b64encode(image_bytes).decode()
        state.update(
            task_id,
            TaskStatus.IMAGE_READY,
            progress_message="图片已生成，请确认或继续",
            image_base64=image_base64,
        )
    except Exception as e:
        state.update(task_id, TaskStatus.FAILED, error=f"图片生成失败: {e}")


def _save_video(task_id: str, prompt: str, video_bytes: bytes) -> Path:
    """Save generated video to output/videos/. Returns saved file path."""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prompt = "".join(c if c.isalnum() or c in " _-" else "_" for c in (prompt or "video")[:30])
    filename = f"{timestamp}_{task_id[:8]}_{safe_prompt}.mp4"
    filepath = VIDEO_DIR / filename
    filepath.write_bytes(video_bytes)
    return filepath


async def run_video_pipeline(
    prompt: str,
    task_id: str,
    state: StateManager,
    video_service: APIMode | CLIMode,
    image_bytes: bytes,
    is_cli_mode: bool = False,
) -> None:
    """Image → Video → Package. image_bytes is the input image."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        image_path = tmp / "input.png"
        image_path.write_bytes(image_bytes)

        # Step 1: Generate video
        state.update(task_id, TaskStatus.GENERATING_VIDEO, "1/2", "正在生成动态视频…")
        try:
            if is_cli_mode:
                assert isinstance(video_service, CLIMode)
                video_url = await video_service.image_to_video(image_path, prompt)
            else:
                assert isinstance(video_service, APIMode)
                seedance_task_id = await video_service.submit(
                    image_bytes=image_bytes,
                    prompt=prompt,
                )
                video_url = await video_service.poll(seedance_task_id)

            video_path = tmp / "output.mp4"
            async with AsyncClient() as client:
                async with client.stream("GET", video_url, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    video_bytes = await resp.aread()
                    video_path.write_bytes(video_bytes)

            saved_path = _save_video(task_id, prompt, video_bytes)
            print(f"[SAVE] Video saved to {saved_path}")
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"视频生成失败: {e}")
            return

        # Step 2: Package Live Photo
        state.update(task_id, TaskStatus.PACKAGING, "2/2", "正在打包 Live Photo…")
        try:
            mov_path, heic_path = await make_livephoto(video_path, tmp)
            zip_path = tmp / "live_photo.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(mov_path, arcname=mov_path.name)
                zf.write(heic_path, arcname=heic_path.name)
            state.update(
                task_id,
                TaskStatus.DONE,
                download_url=f"/api/download/{task_id}",
            )
            _ZIP_STORE[task_id] = zip_path.read_bytes()
            _ZIP_TIMESTAMPS[task_id] = time.time()
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"打包失败: {e}")


_ZIP_STORE: dict[str, bytes] = {}
_ZIP_TIMESTAMPS: dict[str, float] = {}


def get_zip(task_id: str) -> bytes | None:
    return _ZIP_STORE.get(task_id)


def cleanup_zips(ttl: int = 1800) -> int:
    """Remove zip entries older than TTL seconds."""
    now = time.time()
    stale = [
        tid
        for tid, ts in _ZIP_TIMESTAMPS.items()
        if now - ts > ttl
    ]
    for tid in stale:
        _ZIP_STORE.pop(tid, None)
        _ZIP_TIMESTAMPS.pop(tid, None)
    return len(stale)
