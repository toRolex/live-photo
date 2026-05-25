"""Gate 2: Verify Live Photo format conversion works.

Creates a test video from ffmpeg, converts to MOV+HEIC, outputs ZIP for iPhone testing.
"""

import asyncio
import tempfile
from pathlib import Path

from services.livephoto import make_livephoto


async def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Create a 4-second test video (colored bars)
        video_path = tmp / "test.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=4:size=1280x720:rate=30",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(video_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"FAIL: ffmpeg test video creation: {stderr.decode()}")
            return

        print("OK: Test video created")

        # Convert to Live Photo
        mov_path, heic_path = await make_livephoto(video_path, tmp)
        print(f"OK: MOV created at {mov_path}")
        print(f"OK: HEIC created at {heic_path}")
        print()
        print("Transfer both files to iPhone and test in Photos app.")
        print("They should share the same content_identifier for pairing.")


if __name__ == "__main__":
    asyncio.run(main())
