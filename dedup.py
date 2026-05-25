"""IP + prompt SHA256 deduplication (5-minute window)."""

import hashlib


def make_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


DEDUP_WINDOW = 300  # 5 minutes
