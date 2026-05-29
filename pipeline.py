"""Core orchestration: GPT -> Seedance -> ffmpeg -> ZIP."""

import base64
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from httpx import AsyncClient

from services.gpt_image import GPTImageService
from services.livephoto import make_livephoto
from services.seedance import APIMode, CLIMode, VideoConfig
from state import StateManager, TaskStatus

OUTPUT_DIR = Path("output")
IMAGE_DIR = OUTPUT_DIR / "images"
VIDEO_DIR = OUTPUT_DIR / "videos"
LIVE_PHOTO_DIR = OUTPUT_DIR / "live_photos"


def _detect_ext(image_bytes: bytes) -> str:
    """Detect image extension from file header bytes."""
    if image_bytes[:4] == b"\x89PNG":
        return ".png"
    if image_bytes[:2] == b"\xff\xd8":
        return ".jpg"
    if image_bytes[:4] in (b"RIFF", b"WEBP"):
        return ".webp"
    if image_bytes[:4] == b"GIF8":
        return ".gif"
    return ".png"


def _save_image(task_id: str, prompt: str, image_bytes: bytes) -> Path:
    """Save generated image to output/images/. Returns saved file path."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prompt = "".join(c if c.isalnum() or c in " _-" else "_" for c in (prompt or "image")[:30])
    ext = _detect_ext(image_bytes)
    filename = f"{timestamp}_{task_id[:8]}_{safe_prompt}{ext}"
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
    _start = time.time()
    state.update(task_id, TaskStatus.GENERATING_IMAGE, "1/2", "正在生成图片…",
                 timeline_event="开始调用 GPT 图片生成", step_started_at=_start, elapsed_seconds=0,
                 progress_pct=10, estimated_remaining=30)
    try:
        state.update(task_id, TaskStatus.GENERATING_IMAGE,
                     timeline_event="正在连接 AI 服务…", progress_pct=15)
        image_bytes = await gpt_service.generate(prompt)
        _elapsed = round(time.time() - _start, 1)

        image_base64 = base64.b64encode(image_bytes).decode()

        state.update(task_id, TaskStatus.GENERATING_IMAGE,
                     timeline_event="图片数据已接收，正在保存…", progress_pct=90)
        try:
            saved_path = _save_image(task_id, prompt, image_bytes)
            print(f"[SAVE] Image saved to {saved_path}")
        except Exception as save_err:
            print(f"[SAVE] Primary save failed: {save_err}, trying fallback from base64")
            try:
                fallback_path = IMAGE_DIR / f"{task_id[:8]}_fallback.png"
                IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                fallback_path.write_bytes(base64.b64decode(image_base64))
                print(f"[SAVE] Fallback save OK: {fallback_path}")
            except Exception as fb_err:
                print(f"[SAVE] Fallback save also failed: {fb_err}")

        state.update(
            task_id,
            TaskStatus.IMAGE_READY,
            progress_message="图片已生成，请确认或继续",
            image_base64=image_base64,
            timeline_event=f"图片生成完成，耗时 {_elapsed}s",
            elapsed_seconds=_elapsed,
            progress_pct=100,
            estimated_remaining=0,
        )
    except Exception as e:
        state.update(task_id, TaskStatus.FAILED, error=f"图片生成失败: {e}",
                     timeline_event=f"图片生成失败: {e}")


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
    config: VideoConfig,
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
        _v_start = time.time()
        mode_label = "CLI" if is_cli_mode else "API"
        state.update(task_id, TaskStatus.GENERATING_VIDEO, "1/2", "正在生成动态视频…",
                     timeline_event=f"开始视频生成（{mode_label} 模式）", step_started_at=_v_start, elapsed_seconds=0,
                     progress_pct=30, estimated_remaining=120)
        try:
            if is_cli_mode:
                assert isinstance(video_service, CLIMode)
                state.update(task_id, TaskStatus.GENERATING_VIDEO,
                             timeline_event="dreamina CLI 已启动")
                video_url = await video_service.image_to_video(image_path, config)
            else:
                assert isinstance(video_service, APIMode)
                state.update(task_id, TaskStatus.GENERATING_VIDEO,
                             timeline_event="提交任务到 Seedance API")
                seedance_task_id = await video_service.submit(config, image_bytes)
                state.update(task_id, TaskStatus.GENERATING_VIDEO,
                             timeline_event=f"Seedance 任务已提交: {seedance_task_id[:16]}…")

                async def _on_poll(elapsed: float, attempt: int):
                    state.update(task_id, TaskStatus.GENERATING_VIDEO,
                                 timeline_event=f"轮询 #{attempt}，已等待 {int(elapsed)}s",
                                 elapsed_seconds=round(elapsed, 1))

                video_url = await video_service.poll(seedance_task_id, on_progress=_on_poll)

            _v_elapsed = round(time.time() - _v_start, 1)
            state.update(task_id, TaskStatus.GENERATING_VIDEO,
                         timeline_event=f"视频生成完成，耗时 {_v_elapsed}s，开始下载",
                         elapsed_seconds=_v_elapsed)

            video_path = tmp / "output.mp4"
            async with AsyncClient() as client:
                async with client.stream("GET", video_url, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    video_bytes = await resp.aread()
                    video_path.write_bytes(video_bytes)

            saved_path = _save_video(task_id, config.prompt, video_bytes)
            print(f"[SAVE] Video saved to {saved_path}")
            state.update(task_id, TaskStatus.GENERATING_VIDEO,
                         timeline_event=f"视频文件已保存: {saved_path.name}")
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"视频生成失败: {e}",
                         timeline_event=f"视频生成失败: {e}")
            return

        # Step 2: Package Live Photo
        _p_start = time.time()
        state.update(task_id, TaskStatus.PACKAGING, "2/2", "正在打包 Live Photo…",
                     timeline_event="开始 HEIC/MOV 格式转换", step_started_at=_p_start, elapsed_seconds=0,
                     progress_pct=80, estimated_remaining=15)
        try:
            mov_path, heic_path, pvt_path = await make_livephoto(video_path, tmp)
            _p_elapsed = round(time.time() - _p_start, 1)
            state.update(task_id, TaskStatus.PACKAGING,
                         timeline_event="HEIC/MOV 转换完成，开始打包 PVT",
                         elapsed_seconds=_p_elapsed)

            # Save Live Photo files to disk
            LIVE_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
            safe_prompt = "".join(c if c.isalnum() or c in " _-" else "_" for c in (config.prompt or "live_photo")[:30])
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"{timestamp}_{task_id[:8]}_{safe_prompt}"
            saved_mov = LIVE_PHOTO_DIR / f"{prefix}.MOV"
            saved_heic = LIVE_PHOTO_DIR / f"{prefix}.HEIC"
            saved_pvt = LIVE_PHOTO_DIR / f"{prefix}.pvt"

            # .pvt is a directory package, copy recursively
            shutil.copy2(mov_path, saved_mov)
            shutil.copy2(heic_path, saved_heic)
            if pvt_path.is_dir():
                saved_pvt.mkdir(parents=True, exist_ok=True)
                for item in pvt_path.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, saved_pvt / item.name)
                    else:
                        shutil.copy2(item, saved_pvt / item.name)
            print(f"[SAVE] Live Photo saved to {LIVE_PHOTO_DIR} (MOV + HEIC + .pvt)")

            # Create ZIP of .pvt package for download
            zip_path = tmp / "live_photo.pvt.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for item in sorted(pvt_path.rglob('*')):
                    if item.is_file():
                        zf.write(item, arcname=item.relative_to(pvt_path))

            # elapsed_seconds here is total time from video start to packaging done,
            # not just the last step duration. The status endpoint returns this as-is
            # for DONE tasks (does not recalculate via step_started_at).
            total_elapsed = round(time.time() - _v_start, 1)
            state.update(
                task_id,
                TaskStatus.DONE,
                download_url=f"/api/download/{task_id}",
                timeline_event=f"打包完成，总耗时 {total_elapsed}s",
                elapsed_seconds=total_elapsed,
            )
            _ZIP_STORE[task_id] = zip_path.read_bytes()
            _ZIP_TIMESTAMPS[task_id] = time.time()
        except Exception as e:
            state.update(task_id, TaskStatus.FAILED, error=f"打包失败: {e}",
                         timeline_event=f"打包失败: {e}")


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
