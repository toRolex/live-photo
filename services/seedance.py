"""即梦视频生成 — API 模式 + CLI 模式双适配."""

import asyncio
import base64
import dataclasses
import hashlib
import hmac
import io
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from PIL import Image


@dataclasses.dataclass
class VideoConfig:
    """Video generation parameters."""
    prompt: str = ""
    seed: int = -1
    frames: int = 121
    last_frame_bytes: bytes | None = None


def _sign_v4(access_key: str, secret_key: str, method: str, path: str,
             query: str, body: str, x_date: str) -> str:
    """Volcengine SignV4 (HMAC-SHA256) for cn-north-1 / cv service."""
    host = "visual.volcengineapi.com"
    signed_headers = "content-type;host;x-date"
    hashed_body = hashlib.sha256(body.encode()).hexdigest()

    canonical = (
        f"{method}\n{path}\n{query}\n"
        f"content-type:application/json\n"
        f"host:{host}\n"
        f"x-date:{x_date}\n\n"
        f"{signed_headers}\n{hashed_body}"
    )
    algorithm = "HMAC-SHA256"
    date_tag = x_date[:8]
    credential_scope = f"{date_tag}/cn-north-1/cv/request"
    hashed_canonical = hashlib.sha256(canonical.encode()).hexdigest()
    string_to_sign = f"{algorithm}\n{x_date}\n{credential_scope}\n{hashed_canonical}"

    k_date = hmac.new(secret_key.encode(), date_tag.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, b"cn-north-1", hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"cv", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return (
        f"{algorithm} "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class APIMode:
    """火山引擎 CVSync2AsyncSubmitTask / CVSync2AsyncGetResult — 即梦视频生成 3.0."""

    ENDPOINT = "https://visual.volcengineapi.com"
    REQ_KEY = "jimeng_i2v_first_v30"

    def __init__(self, access_key: str, secret_key: str) -> None:
        self._ak = access_key
        self._sk = secret_key
        self._client = httpx.AsyncClient(timeout=120)

    @staticmethod
    def _compress_image(image_bytes: bytes, max_size: tuple = (1280, 720)) -> bytes:
        """Compress image for API submission."""
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    async def submit(self, config: VideoConfig, image_bytes: bytes) -> str:
        """Submit image-to-video task, return task_id."""
        query = urlencode({
            "Action": "CVSync2AsyncSubmitTask",
            "Version": "2022-08-31",
        })
        # Compress image if too large (>2MB)
        if len(image_bytes) > 2 * 1024 * 1024:
            image_bytes = self._compress_image(image_bytes)
        img_parts = [base64.b64encode(image_bytes).decode()]
        if config.last_frame_bytes:
            img_parts.append(base64.b64encode(config.last_frame_bytes).decode())

        body = json.dumps({
            "req_key": self.REQ_KEY,
            "binary_data_base64": img_parts,
            "prompt": (config.prompt or "")[:800],
            "seed": config.seed,
            "frames": config.frames,
        })

        x_date = _now_utc()
        auth = _sign_v4(self._ak, self._sk, "POST", "/", query, body, x_date)

        resp = await self._client.post(
            f"{self.ENDPOINT}?{query}",
            headers={
                "Content-Type": "application/json",
                "Host": "visual.volcengineapi.com",
                "X-Date": x_date,
                "Authorization": auth,
            },
            content=body,
        )
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(
                f"Seedance API 返回非 JSON 响应 (status={resp.status_code}): "
                f"{resp.text[:500]}"
            ) from e
        if data.get("code") != 10000:
            raise RuntimeError(f"Seedance API error: {data}")
        return data["data"]["task_id"]

    async def poll(self, task_id: str, interval: int = 5, timeout: int = 600,
                  on_progress: Callable[[float, int], Awaitable[None]] | None = None) -> str:
        """Poll until task is done, return video_url."""
        query = urlencode({
            "Action": "CVSync2AsyncGetResult",
            "Version": "2022-08-31",
        })

        deadline = time.time() + timeout
        start = time.time()
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            body = json.dumps({"req_key": self.REQ_KEY, "task_id": task_id})
            x_date = _now_utc()
            auth = _sign_v4(self._ak, self._sk, "POST", "/", query, body, x_date)

            resp = await self._client.post(
                f"{self.ENDPOINT}?{query}",
                headers={
                    "Content-Type": "application/json",
                    "Host": "visual.volcengineapi.com",
                    "X-Date": x_date,
                    "Authorization": auth,
                },
                content=body,
            )
            try:
                data = resp.json()
            except Exception as e:
                raise RuntimeError(
                    f"Seedance poll 返回非 JSON 响应 (status={resp.status_code}): "
                    f"{resp.text[:500]}"
                ) from e
            if data.get("code") != 10000:
                raise RuntimeError(f"Seedance poll error: {data}")
            status = data["data"].get("status")
            if status == "done":
                return data["data"]["video_url"]
            if status == "failed":
                raise RuntimeError(f"Seedance task failed: {data['data']}")
            if on_progress:
                elapsed = time.time() - start
                await on_progress(elapsed, attempt)
            await asyncio.sleep(interval)
        raise TimeoutError("Seedance video generation timed out")


class CLIMode:
    """dreamina_cli subprocess adapter."""

    def __init__(self, poll_interval: int = 30) -> None:
        self._poll = poll_interval

    async def image_to_video(self, image_path: str | Path, config: VideoConfig) -> str:
        """Run dreamina image2video, return video URL."""
        duration = 5 if config.frames <= 121 else 10
        cmd = [
            "dreamina", "image2video",
            "--images", str(image_path),
            "--duration", str(duration),
            "--ratio", "16:9",
            "--video_resolution", "720P",
            "--poll", str(self._poll),
        ]
        if config.prompt:
            cmd += ["--prompt", (config.prompt)[:800]]
        if config.seed >= 0:
            cmd += ["--seed", str(config.seed)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"dreamina CLI failed: {stderr.decode()}")
        output = stdout.decode()
        # CLI outputs URL in stdout; parse last line
        for line in output.strip().splitlines():
            if line.startswith("http"):
                return line.strip()
        raise RuntimeError(f"No video URL in CLI output: {output}")

    async def check_login(self) -> bool:
        """Run dreamina user_credit to check login status."""
        proc = await asyncio.create_subprocess_exec(
            "dreamina", "user_credit",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, _ = await proc.communicate()
        return proc.returncode == 0


def get_service(mode: str, **kwargs) -> APIMode | CLIMode:
    """Factory: mode='api' or 'cli'."""
    if mode == "api":
        return APIMode(kwargs["access_key"], kwargs["secret_key"])
    return CLIMode()
