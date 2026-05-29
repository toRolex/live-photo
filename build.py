"""Build script — packages Live Photo Maker into a standalone distributable.

Usage:
  python build.py            # Build for current platform
  python build.py --zip      # Build + create distributable ZIP
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
DIST = ROOT / "dist" / "live-photo-dist"

# ── ffmpeg download ──────────────────────────────────────────────────

# Primary: BtbN auto-builds (GitHub, usually accessible). Fallback: gyan.dev.
_FFMPEG_WIN_URLS = [
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]
FFMPEG_MAC_URL = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"


def _http_get(url: str, dest: str, retries: int = 3) -> None:
    """Download `url` to `dest` with retry + exponential backoff."""
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            Path(dest).write_bytes(data)
            return
        except Exception as e:
            last_err = e
            if i < retries - 1:
                wait = (i + 1) * 5
                print(f"[BUILD] Download failed, retrying in {wait}s… ({e})")
                time.sleep(wait)
    raise RuntimeError(f"Download failed after {retries} attempts: {last_err}")


def download_ffmpeg_win(target_dir: Path) -> Path:
    """Download ffmpeg for Windows, extract ffmpeg.exe into target_dir."""
    for url in _FFMPEG_WIN_URLS:
        try:
            print(f"[BUILD] Downloading ffmpeg: {url}")
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            tmp.close()
            _http_get(url, tmp.name, retries=2)
            with zipfile.ZipFile(tmp.name) as zf:
                for name in zf.namelist():
                    if name.endswith("/bin/ffmpeg.exe") or name == "ffmpeg.exe":
                        zf.extract(name, target_dir)
                        extracted = target_dir / name
                        dest = target_dir / "ffmpeg.exe"
                        shutil.move(str(extracted), str(dest))
                        top_dir = name.split("/")[0]
                        if top_dir != "ffmpeg.exe":
                            shutil.rmtree(target_dir / top_dir, ignore_errors=True)
                        print(f"[BUILD] ffmpeg.exe extracted to {dest}")
                        return dest
            print(f"[BUILD] ffmpeg.exe not found in {url}, trying next URL…")
        except Exception as e:
            print(f"[BUILD] Failed: {e}")
    raise RuntimeError("Could not download ffmpeg from any source")


def download_ffmpeg_mac(target_dir: Path) -> Path:
    """Download ffmpeg for macOS."""
    print("[BUILD] Downloading ffmpeg for macOS...")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    urllib.request.urlretrieve(FFMPEG_MAC_URL, tmp.name)
    with zipfile.ZipFile(tmp.name) as zf:
        zf.extractall(target_dir)
    dest = target_dir / "ffmpeg"
    dest.chmod(0o755)
    print(f"[BUILD] ffmpeg extracted to {dest}")
    return dest


def ensure_ffmpeg(cache_dir: Path) -> Path:
    """Download ffmpeg to cache_dir once, return path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        dest = cache_dir / "ffmpeg.exe"
        if not dest.exists():
            download_ffmpeg_win(cache_dir)
        return dest
    else:
        dest = cache_dir / "ffmpeg"
        if not dest.exists():
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                shutil.copy(system_ffmpeg, dest)
                dest.chmod(0o755)
            else:
                download_ffmpeg_mac(cache_dir)
        return dest


# ── Build ────────────────────────────────────────────────────────────


def run_pyinstaller():
    print("[BUILD] Running PyInstaller...")
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "live-photo.spec"],
        cwd=str(ROOT),
    )


def create_zip():
    """Create a distributable ZIP file."""
    zip_name = f"live-photo-maker-{sys.platform}.zip"
    zip_path = ROOT / zip_name
    print(f"[BUILD] Creating {zip_name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DIST.rglob("*"):
            zf.write(f, f.relative_to(DIST))
    print(f"[BUILD] Done: {zip_path}")
    return zip_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", action="store_true", help="Create distributable ZIP after build")
    args = parser.parse_args()

    print(f"[BUILD] Platform: {sys.platform}")
    print(f"[BUILD] Python: {sys.version}")

    ffmpeg_path = ensure_ffmpeg(CACHE)

    run_pyinstaller()
    shutil.copy2(ffmpeg_path, DIST / ffmpeg_path.name)
    print(f"[BUILD] ffmpeg copied from cache to {DIST}")

    print(f"[BUILD] Output: {DIST}")
    print("[BUILD] To run: double-click live-photo.exe (Windows) or ./live-photo (macOS/Linux)")

    if args.zip:
        create_zip()


if __name__ == "__main__":
    main()
