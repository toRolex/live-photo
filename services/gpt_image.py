"""GPT-image-2 API wrapper via OpenAI-compatible Chat Completions proxy."""

import base64
import binascii
import re

import httpx
from openai import AsyncOpenAI


class GPTImageService:
    def __init__(self, api_key: str, base_url: str = "https://wcnb.ai/v1") -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    async def generate(self, prompt: str) -> bytes:
        """Generate an image via Chat Completions streaming. Returns PNG bytes."""
        stream = await self._client.chat.completions.create(
            model="gpt-image-2",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )

        content_parts: list[str] = []
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                content_parts.append(delta.content)

        full_content = "".join(content_parts)

        # Try base64 data URL first
        b64_match = re.search(r"data:image/\w+;base64,([A-Za-z0-9+/=]+)", full_content)
        if b64_match:
            return base64.b64decode(b64_match.group(1))

        try:
            return base64.b64decode(full_content)
        except (ValueError, binascii.Error):
            pass

        # Try markdown image URL: ![image](https://...)
        url_match = re.search(r"\]\((https?://[^)]+)\)", full_content)
        if url_match:
            img_url = url_match.group(1)
            resp = await self._http.get(img_url)
            resp.raise_for_status()
            return resp.content

        raise RuntimeError(f"GPT response does not contain valid image data: {full_content[:200]}")

    async def close(self) -> None:
        await self._http.aclose()
