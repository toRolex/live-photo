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
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "live-photo-dist"

# ── ffmpeg download ──────────────────────────────────────────────────

FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_MAC_URL = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"


def download_ffmpeg_win(target_dir: Path) -> Path:
    """Download ffmpeg for Windows, extract ffmpeg.exe into target_dir."""
    print("[BUILD] Downloading ffmpeg for Windows...")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    urllib.request.urlretrieve(FFMPEG_WIN_URL, tmp.name)
    with zipfile.ZipFile(tmp.name) as zf:
        for name in zf.namelist():
            if name.endswith("/bin/ffmpeg.exe"):
                zf.extract(name, target_dir)
                extracted = target_dir / name
                dest = target_dir / "ffmpeg.exe"
                shutil.move(str(extracted), str(dest))
                # Clean up extracted dirs
                top_dir = name.split("/")[0]
                shutil.rmtree(target_dir / top_dir, ignore_errors=True)
                print(f"[BUILD] ffmpeg.exe extracted to {dest}")
                return dest
    raise RuntimeError("ffmpeg.exe not found in downloaded archive")


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


def ensure_ffmpeg(target_dir: Path) -> Path:
    """Ensure ffmpeg binary exists in target_dir."""
    if sys.platform == "win32":
        dest = target_dir / "ffmpeg.exe"
        if not dest.exists():
            download_ffmpeg_win(target_dir)
        return dest
    else:
        dest = target_dir / "ffmpeg"
        if not dest.exists():
            # On macOS/Linux, copy from system if available
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                shutil.copy(system_ffmpeg, dest)
                dest.chmod(0o755)
            else:
                download_ffmpeg_mac(target_dir)
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

    run_pyinstaller()
    ensure_ffmpeg(DIST)

    print(f"[BUILD] Output: {DIST}")
    print("[BUILD] To run: double-click live-photo.exe (Windows) or ./live-photo (macOS/Linux)")

    if args.zip:
        create_zip()


if __name__ == "__main__":
    main()
