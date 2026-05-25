"""GPT-image-2 API wrapper."""

import base64

from openai import AsyncOpenAI


class GPTImageService:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def generate(self, prompt: str) -> bytes:
        """Generate an image from text prompt. Returns PNG bytes."""
        response = await self._client.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            size="1024x1024",
            n=1,
            response_format="b64_json",
        )
        if not response.data:
            raise RuntimeError("GPT image generation returned no data")
        b64 = response.data[0].b64_json
        if b64 is None:
            raise RuntimeError("GPT image generation returned empty response")
        return base64.b64decode(b64)
