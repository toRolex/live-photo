"""FastAPI entry point — Live Photo Maker."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from dedup import DEDUP_WINDOW, make_prompt_hash
from pipeline import get_zip, run_pipeline
from services.gpt_image import GPTImageService
from services.seedance import get_service
from state import StateManager

# --- Configuration ---
GPT_API_KEY = os.getenv("OPENAI_API_KEY", "")
SEEDANCE_AK = os.getenv("SEEDANCE_ACCESS_KEY", "")
SEEDANCE_SK = os.getenv("SEEDANCE_SECRET_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not GPT_API_KEY:
        print("WARNING: OPENAI_API_KEY not set. GPT image generation will fail.")
    app.state.manager = StateManager()
    app.state.gpt = GPTImageService(GPT_API_KEY) if GPT_API_KEY else None
    app.state.video_cli = get_service(mode="cli")
    app.state.video_api = get_service(
        mode="api",
        access_key=SEEDANCE_AK,
        secret_key=SEEDANCE_SK,
    ) if SEEDANCE_AK and SEEDANCE_SK else None
    timer = asyncio.create_task(_cleanup_loop(app.state.manager))
    yield
    timer.cancel()


app = FastAPI(title="Live Photo Maker", lifespan=lifespan)


async def _cleanup_loop(state_manager: StateManager):
    """Periodically cleanup stale tasks."""
    while True:
        await asyncio.sleep(300)
        state_manager.cleanup_stale()


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse((Path("static") / "index.html").read_text())


@app.post("/api/generate")
async def generate(request: Request):
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()

    if not prompt:
        raise HTTPException(400, "输入不能为空")
    if len(prompt) > 500:
        raise HTTPException(400, "输入超过 500 字符限制")

    # Frontend-selected mode: "cli" (default) or "api"
    mode = body.get("mode", "cli")
    if mode not in ("cli", "api"):
        mode = "cli"
    is_cli = mode == "cli"

    ip = request.client.host if request.client else "unknown"
    prompt_hash = make_prompt_hash(prompt)

    manager: StateManager = app.state.manager

    # Dedup
    existing = manager.find_by_ip_prompt(ip, prompt_hash, DEDUP_WINDOW)
    if existing:
        return {"task_id": existing.task_id, "dedup": True}

    task_id = str(uuid.uuid4())
    try:
        manager.create(task_id, ip, prompt_hash)
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    # Get video service based on frontend choice
    video = app.state.video_cli if is_cli else app.state.video_api

    # Fire pipeline in background
    asyncio.create_task(
        run_pipeline(
            prompt=prompt,
            task_id=task_id,
            state=manager,
            gpt_service=app.state.gpt,
            video_service=video,
            is_cli_mode=is_cli,
        )
    )

    return {"task_id": task_id}


@app.get("/api/status/{task_id}")
async def status(task_id: str):
    manager: StateManager = app.state.manager
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "step_index": task.step_index,
        "progress_message": task.progress_message,
        "download_url": task.download_url,
        "error": task.error,
    }


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
