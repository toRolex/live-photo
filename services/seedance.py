"""即梦视频生成 — API 模式 + CLI 模式双适配."""

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlencode


class APIMode:
    """火山引擎 CVSync2AsyncSubmitTask / CVSync2AsyncGetResult."""

    ENDPOINT = "https://visual.volcengineapi.com"

    def __init__(self, access_key: str, secret_key: str) -> None:
        self._ak = access_key
        self._sk = secret_key

    async def submit(self, image_url: str, prompt: str = "", aspect_ratio: str = "16:9") -> str:
        """Submit image-to-video task, return task_id."""
        query = urlencode({
            "Action": "CVSync2AsyncSubmitTask",
            "Version": "2022-08-31",
        })

        body = json.dumps({
            "req_key": "jimeng_vgfm_i2v_l20",
            "image_urls": [image_url],
            "prompt": prompt[:150],
            "aspect_ratio": aspect_ratio,
        })

        # Simplified: in production, use volcengine-python-sdk for signing
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.ENDPOINT}?{query}",
                headers={"Content-Type": "application/json"},
                content=body,
                timeout=30,
            )
        data = resp.json()
        if data.get("code") != 10000:
            raise RuntimeError(f"Seedance API error: {data}")
        return data["data"]["task_id"]

    async def poll(self, task_id: str, interval: int = 5, timeout: int = 600) -> str:
        """Poll until task is done, return video_url."""
        import httpx

        query = urlencode({
            "Action": "CVSync2AsyncGetResult",
            "Version": "2022-08-31",
        })

        deadline = time.time() + timeout
        while time.time() < deadline:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.ENDPOINT}?{query}",
                    headers={"Content-Type": "application/json"},
                    content=json.dumps({
                        "req_key": "jimeng_vgfm_i2v_l20",
                        "task_id": task_id,
                    }),
                    timeout=30,
                )
            data = resp.json()
            if data.get("code") != 10000:
                raise RuntimeError(f"Seedance poll error: {data}")
            status = data["data"].get("status")
            if status == "done":
                return data["data"]["video_url"]
            await asyncio.sleep(interval)
        raise TimeoutError("Seedance video generation timed out")


class CLIMode:
    """dreamina_cli subprocess adapter."""

    def __init__(self, poll_interval: int = 30) -> None:
        self._poll = poll_interval

    async def image_to_video(self, image_path: str | Path, prompt: str = "") -> str:
        """Run dreamina image2video, return video URL."""
        cmd = [
            "dreamina", "image2video",
            "--images", str(image_path),
            "--duration", "5",
            "--ratio", "16:9",
            "--video_resolution", "720P",
            "--poll", str(self._poll),
        ]
        if prompt:
            cmd += ["--prompt", prompt[:150]]

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
