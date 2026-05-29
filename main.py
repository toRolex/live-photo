"""FastAPI entry point — Live Photo Maker."""

import asyncio
import base64
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv(override=True)
from fastapi.responses import HTMLResponse, Response  # noqa: E402

from dedup import DEDUP_WINDOW, make_prompt_hash
from pipeline import _save_image, cleanup_zips, get_zip, run_image_only, run_video_pipeline
from services.gpt_image import GPTImageService
from services.seedance import APIMode, VideoConfig, get_service
from state import StateManager, TaskStatus

GPT_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://wcnb.ai/v1")
SEEDANCE_AK = os.getenv("SEEDANCE_ACCESS_KEY", "")
SEEDANCE_SK = os.getenv("SEEDANCE_SECRET_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not GPT_API_KEY:
        print("WARNING: OPENAI_API_KEY not set. GPT image generation will fail.")
    app.state.manager = StateManager()
    app.state.gpt = GPTImageService(GPT_API_KEY, GPT_BASE_URL) if GPT_API_KEY else None
    app.state.video_cli = get_service(mode="cli")
    app.state.video_api = get_service(
        mode="api",
        access_key=SEEDANCE_AK,
        secret_key=SEEDANCE_SK,
    ) if SEEDANCE_AK and SEEDANCE_SK else None
    timer = asyncio.create_task(_cleanup_loop(app.state.manager))
    yield
    timer.cancel()
    try:
        await timer
    except asyncio.CancelledError:
        pass
    if app.state.video_api and isinstance(app.state.video_api, APIMode):
        await app.state.video_api._client.aclose()
    if app.state.gpt:
        await app.state.gpt.close()


app = FastAPI(title="Live Photo Maker", lifespan=lifespan)


async def _cleanup_loop(state_manager: StateManager):
    while True:
        await asyncio.sleep(300)
        state_manager.cleanup_stale()
        cleanup_zips(1800)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse((Path("static") / "index.html").read_text())


def _normalize_mode(raw: object, default: str = "cli") -> str:
    if isinstance(raw, str) and raw in ("cli", "api"):
        return raw
    return default


@app.post("/api/generate-image")
async def generate_image(request: Request):
    """Text → GPT image. Returns image as base64 in status."""
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()

    if not prompt:
        raise HTTPException(400, "输入不能为空")
    if len(prompt) > 500:
        raise HTTPException(400, "输入超过 500 字符限制")

    if not app.state.gpt:
        raise HTTPException(503, "图片生成服务未配置（缺少 OPENAI_API_KEY）")

    ip = request.client.host if request.client else "unknown"
    prompt_hash = make_prompt_hash(prompt)
    manager: StateManager = app.state.manager

    existing = manager.find_by_ip_prompt(ip, prompt_hash, DEDUP_WINDOW)
    if existing:
        return {"task_id": existing.task_id, "dedup": True}

    task_id = str(uuid.uuid4())
    try:
        manager.create(task_id, ip, prompt, prompt_hash)
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    asyncio.create_task(
        run_image_only(
            prompt=prompt,
            task_id=task_id,
            state=manager,
            gpt_service=app.state.gpt,
        )
    )

    return {"task_id": task_id}


@app.post("/api/upload-image")
async def upload_image(request: Request):
    """Upload an image — directly set IMAGE_READY, no background task."""
    form = await request.form()
    raw = form.get("file")
    file = raw if hasattr(raw, "filename") and hasattr(raw, "read") else None

    if not file or not file.filename:
        raise HTTPException(400, "请上传图片文件")

    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(400, "图片文件不能超过 20MB")

    ip = request.client.host if request.client else "unknown"
    manager: StateManager = app.state.manager

    task_id = str(uuid.uuid4())
    try:
        manager.create(task_id, ip, "", "")
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    image_base64 = base64.b64encode(image_bytes).decode()
    try:
        saved_path = _save_image(task_id, file.filename, image_bytes)
        print(f"[SAVE] Uploaded image saved to {saved_path}")
    except Exception as save_err:
        print(f"[SAVE] Upload save failed: {save_err}")
    manager.update(
        task_id,
        TaskStatus.IMAGE_READY,
        progress_message="图片已上传，请确认或继续",
        image_base64=image_base64,
        timeline_event=f"图片已上传: {file.filename}",
    )

    return {"task_id": task_id}


@app.post("/api/generate-video")
async def generate_video(request: Request):
    """Continue with video generation using the image from a completed image task."""
    body = await request.json()
    task_id = (body.get("task_id") or "").strip()
    mode = _normalize_mode(body.get("mode"))

    if not task_id:
        raise HTTPException(400, "缺少 task_id")

    manager: StateManager = app.state.manager
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    if task.status != TaskStatus.IMAGE_READY:
        raise HTTPException(400, f"当前状态不允许生成视频: {task.status.value}")
    if not task.image_base64:
        raise HTTPException(400, "没有可用的图片数据")

    # Video settings: default to image prompt, allow override
    video_prompt = body.get("video_prompt") or task.prompt
    video_seed = body.get("video_seed", -1)
    video_frames = body.get("video_frames", 121)
    last_frame_b64 = body.get("last_frame_base64")
    last_frame_bytes = base64.b64decode(last_frame_b64) if last_frame_b64 else None

    config = VideoConfig(
        prompt=video_prompt,
        seed=video_seed,
        frames=video_frames,
        last_frame_bytes=last_frame_bytes,
    )

    # Save video_prompt to task state for poll recovery
    manager.update(task_id, task.status, video_prompt=video_prompt)

    image_bytes = base64.b64decode(task.image_base64)
    is_cli = mode == "cli"
    video = app.state.video_cli if is_cli else app.state.video_api
    if video is None:
        raise HTTPException(503, "视频生成服务未配置")

    asyncio.create_task(
        run_video_pipeline(
            config=config,
            task_id=task_id,
            state=manager,
            video_service=video,
            image_bytes=image_bytes,
            is_cli_mode=is_cli,
        )
    )

    return {"task_id": task_id}


# ── One-shot (legacy compatibility) ────────────────────────────────────


@app.post("/api/generate")
async def generate(request: Request):
    """Legacy one-shot: text → image → video → package."""
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()

    if not prompt:
        raise HTTPException(400, "输入不能为空")
    if len(prompt) > 500:
        raise HTTPException(400, "输入超过 500 字符限制")

    mode = _normalize_mode(body.get("mode"))
    is_cli = mode == "cli"

    if not app.state.gpt:
        raise HTTPException(503, "图片生成服务未配置（缺少 OPENAI_API_KEY）")

    ip = request.client.host if request.client else "unknown"
    prompt_hash = make_prompt_hash(prompt)
    manager: StateManager = app.state.manager

    existing = manager.find_by_ip_prompt(ip, prompt_hash, DEDUP_WINDOW)
    if existing:
        return {"task_id": existing.task_id, "dedup": True}

    task_id = str(uuid.uuid4())
    try:
        manager.create(task_id, ip, prompt, prompt_hash)
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    video = app.state.video_cli if is_cli else app.state.video_api
    if video is None:
        raise HTTPException(503, "视频生成服务未配置")

    async def _run_one_shot():
        """One-shot: generate image then immediately continue to video."""
        try:
            await run_image_only(prompt, task_id, manager, app.state.gpt)
            task = manager.get(task_id)
            if task is None or task.status != TaskStatus.IMAGE_READY:
                return
            image_bytes = base64.b64decode(task.image_base64) if task.image_base64 else None
            if not image_bytes:
                manager.update(task_id, TaskStatus.FAILED, error="图片数据无效")
                return
            config = VideoConfig(prompt=prompt)
            await run_video_pipeline(
                config=config,
                task_id=task_id,
                state=manager,
                video_service=video,
                image_bytes=image_bytes,
                is_cli_mode=is_cli,
            )
        except Exception as e:
            manager.update(task_id, TaskStatus.FAILED, error=f"生成失败: {e}")

    asyncio.create_task(_run_one_shot())

    return {"task_id": task_id}


# ── Status / Download ──────────────────────────────────────────────────


@app.get("/api/status/{task_id}")
async def status(task_id: str):
    manager: StateManager = app.state.manager
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    current_elapsed = task.elapsed_seconds
    current_remaining = task.estimated_remaining
    if task.step_started_at > 0 and task.status not in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.IMAGE_READY):
        current_elapsed = round(time.time() - task.step_started_at, 1)
        if task.estimated_remaining > 0:
            current_remaining = max(0, task.estimated_remaining - current_elapsed)
    result = {
        "task_id": task.task_id,
        "status": task.status.value,
        "step_index": task.step_index,
        "progress_message": task.progress_message,
        "download_url": task.download_url,
        "error": task.error,
        "elapsed_seconds": current_elapsed,
        "progress_timeline": task.progress_timeline,
        "progress_pct": task.progress_pct,
        "estimated_remaining": round(current_remaining, 1),
    }
    if task.status == TaskStatus.IMAGE_READY:
        result["image_base64"] = task.image_base64
        result["video_prompt"] = task.video_prompt or task.prompt
    return result


@app.get("/api/download/{task_id}")
async def download(task_id: str):
    zip_bytes = get_zip(task_id)
    if zip_bytes is None:
        raise HTTPException(404, "文件已过期")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=live_photo_{task_id[:8]}.zip"},
    )
