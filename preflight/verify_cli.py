"""Gate 1: Verify dreamina_cli is available and logged in."""

import asyncio
import subprocess
import sys


async def verify_cli() -> bool:
    """Check dreamina_cli is installed and logged in."""
    # Check installation
    proc = await asyncio.create_subprocess_exec(
        "dreamina", "-h",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        print("FAIL: dreamina CLI not found. Install with:")
        print("  curl -fsSL https://jimeng.jianying.com/cli | bash")
        return False

    print("OK: dreamina CLI is installed")

    # Check login
    proc = await asyncio.create_subprocess_exec(
        "dreamina", "user_credit",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        print("FAIL: Not logged in. Run: dreamina login")
        return False

    print("OK: dreamina CLI is logged in")
    print(f"Credit info: {stdout.decode().strip()}")
    return True


async def verify_ffmpeg() -> bool:
    """Check ffmpeg is available."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-version",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, _ = await proc.communicate()
    if proc.returncode != 0:
        print("FAIL: ffmpeg not found. Install with: brew install ffmpeg")
        return False
    print("OK: ffmpeg is available")
    return True


async def main():
    ok = True
    if not await verify_cli():
        ok = False
    if not await verify_ffmpeg():
        ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
