"""Read MP4 metadata before registering the uploaded object."""

import json
import subprocess
import tempfile
from pathlib import Path


def probe_mp4(data: bytes) -> float:
    """ffprobe로 MP4의 영상 스트림과 재생 시간을 검증한다."""
    with tempfile.TemporaryDirectory(prefix="cctv-probe-") as directory:
        path = Path(directory) / "upload.mp4"
        path.write_bytes(data)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    if result.returncode:
        raise ValueError("invalid_video")
    metadata = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "video" for stream in metadata.get("streams", [])):
        raise ValueError("no_video_stream")
    duration = float(metadata.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise ValueError("invalid_duration")
    return duration
