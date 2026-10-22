"""Make the tiny black videos that keep a phone's screen on where Screen Wake Lock is missing.

A muted, looping, inline video is what browsers let play without asking and what keeps a phone awake
(the technique of NoSleep.js). Ours: 2 s of 16x16 black, no audio track (an audio track can take the
phone's audio session from the band's music), an MP4 for iPhones and a WebM for the rest.

    uv run python scripts/awake_video.py      # writes src/woodshed/page/assets/awake/awake.mp4 and .webm
    uv run python scripts/check_repo.py . --pin-vendored     # then pin their new hashes
"""

from __future__ import annotations

import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "woodshed" / "page" / "assets" / "awake"
SOURCE = ["-f", "lavfi", "-i", "color=c=black:s=16x16:r=5:d=2"]
MP4 = ["-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
WEBM = ["-c:v", "libvpx", "-b:v", "8k"]
CLEAN = ["-an", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]


def main() -> None:
    for name, codec in (("awake.mp4", MP4), ("awake.webm", WEBM)):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *SOURCE, *codec, *CLEAN, str(OUT / name)]
        subprocess.run(cmd, check=True)
        print(f"{name}: {(OUT / name).stat().st_size} bytes")


if __name__ == "__main__":
    main()
