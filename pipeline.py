"""Core orchestration: GPT -> Seedance -> ffmpeg -> ZIP."""

import tempfile
import zipfile
from pathlib import Path

from httpx import AsyncClient

from services.gpt_image import GPTImageService
from services.livephoto import make_livephoto
from services.seedance import APIMode, CLIMode
from state import StateManager, TaskStatus


async def run_pipeline(
    prompt: str,
    task_id: str,
    state: StateManager,
    gpt_service: GPTImageService,
    video_service: APIMode | CLIMode,
    is_cli_mode: bool = False,
) -> None:
    """Execute the full generation pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: Generate image
        state.update(task_id, TaskStatus.GENERATING_IMAGE, "1/3", "正在生成图片…")
        try:
            image_bytes = await gpt_service.generate(prompt)
            image_path = tmp / "input.png"
            image_path.write_bytes(image_bytes)
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"图片生成失败: {e}")
            return

        # Step 2: Generate video
        state.update(task_id, TaskStatus.GENERATING_VIDEO, "2/3", "正在生成动态视频…")
        try:
            if is_cli_mode:
                assert isinstance(video_service, CLIMode)
                video_url = await video_service.image_to_video(image_path)
            else:
                assert isinstance(video_service, APIMode)
                # Upload image to a public URL (e.g., temp S3/OSS) then submit
                image_url = await _upload_image(image_path)
                seedance_task_id = await video_service.submit(
                    image_url=image_url,
                    prompt=prompt,
                )
                video_url = await video_service.poll(seedance_task_id)

            # Download video
            video_path = tmp / "output.mp4"
            async with AsyncClient() as client:
                async with client.stream("GET", video_url, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    video_path.write_bytes(await resp.aread())
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"视频生成失败: {e}")
            return

        # Step 3: Package Live Photo
        state.update(task_id, TaskStatus.PACKAGING, "3/3", "正在打包 Live Photo…")
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
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"打包失败: {e}")
            return


async def _upload_image(image_path: Path) -> str:
    """Upload image to public storage and return URL.
    TODO: Implement actual OSS/S3 upload. For now, returns file:// URI for testing.
    """
    return f"file://{image_path}"


_ZIP_STORE: dict[str, bytes] = {}


def get_zip(task_id: str) -> bytes | None:
    return _ZIP_STORE.get(task_id)
