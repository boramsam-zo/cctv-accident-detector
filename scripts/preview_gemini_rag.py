"""Preview VLM-to-RAG JSON from a local clip or signed S3 evidence.

Place a clip at .local/clip.mp4, optionally with .local/frame.png. The local
.env supplies GEMINI_API_KEY unless the shell overrides it. Media and signed
URLs are read in memory and never printed or saved by this script.
"""

import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from google.genai.errors import APIError, ServerError

from services.backend.gemini_vlm import GeminiVLM


MAX_MEDIA_BYTES = 18 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def local_setting(name: str) -> str | None:
    """환경 변수 또는 저장소의 로컬 .env에서 설정값 하나를 읽는다."""
    if name in os.environ:
        return os.environ[name]
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip('"\'')
    return None


def read_local(path: Path, remaining: int, label: str) -> bytes:
    """로컬 근거 파일을 크기 제한 안에서 읽는다."""
    if not path.is_file():
        raise ValueError(f"{label}: 로컬 파일을 찾을 수 없습니다: {path}")
    if path.stat().st_size > remaining:
        raise ValueError(f"{label}: Gemini inline 입력 크기 상한을 초과했습니다")
    with path.open("rb") as source:
        blob = source.read(remaining + 1)
    if not blob or len(blob) > remaining:
        raise ValueError(f"{label}: 파일이 비어 있거나 입력 크기 상한을 초과했습니다")
    return blob


def fetch_signed_s3(url: str, remaining: int, label: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".amazonaws.com"):
        raise ValueError(f"{label}: AWS S3 HTTPS presigned URL이 필요합니다")
    try:
        with urlopen(url, timeout=30) as response:
            size = response.headers.get("Content-Length")
            if size is not None and int(size) > remaining:
                raise ValueError(f"{label}: Gemini inline 입력 크기 상한을 초과했습니다")
            blob = response.read(remaining + 1)
    except URLError:
        raise RuntimeError(f"{label}: 다운로드 실패. presigned URL 만료 여부를 확인하세요") from None
    if not blob or len(blob) > remaining:
        raise ValueError(f"{label}: 파일이 비어 있거나 입력 크기 상한을 초과했습니다")
    return blob


def main() -> None:
    """로컬 파일 또는 S3 URL의 clip·frame을 Gemini에 보내 RAG 입력을 출력한다."""
    key = local_setting("GEMINI_API_KEY")
    clip_url = os.getenv("CLIP_PRESIGNED_URL")
    image_url = os.getenv("IMAGE_PRESIGNED_URL")
    clip_path = Path(os.getenv("CLIP_FILE", PROJECT_ROOT / ".local" / "clip.mp4"))
    image_path = Path(os.getenv("IMAGE_FILE", PROJECT_ROOT / ".local" / "frame.png"))
    if not key:
        raise SystemExit("GEMINI_API_KEY를 환경 변수 또는 .env에 설정하세요")
    if os.getenv("CLIP_FILE") or clip_path.is_file():
        clip = read_local(clip_path, MAX_MEDIA_BYTES, "clip")
    elif clip_url:
        clip = fetch_signed_s3(clip_url, MAX_MEDIA_BYTES, "clip")
    else:
        raise SystemExit(f"clip을 {clip_path}에 놓거나 CLIP_PRESIGNED_URL을 설정하세요")
    if len(clip) < 12 or clip[4:8] != b"ftyp":
        raise SystemExit("clip: MP4 파일 내용이 아닙니다")
    media = [("sample-clip", "video/mp4", clip)]
    if os.getenv("IMAGE_FILE") or image_path.is_file():
        image = read_local(image_path, MAX_MEDIA_BYTES - len(clip), "image")
    elif image_url:
        image = fetch_signed_s3(image_url, MAX_MEDIA_BYTES - len(clip), "image")
    else:
        image = None
    if image is not None:
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit("image: PNG 파일 내용이 아닙니다")
        media.append(("sample-frame", "image/png", image))
    candidate = os.getenv("CANDIDATE_TIME_S")
    event = {"event_id": os.getenv("EVENT_ID", "event_000"),
             "candidate_time_s": float(candidate) if candidate else None,
             "start_seconds": None, "end_seconds": None,
             "object_observations": []}
    try:
        result = GeminiVLM(key, local_setting("GEMINI_MODEL") or "gemini-3.6-flash").analyze(event, media)
    except ServerError:
        raise SystemExit("Gemini 서비스가 일시적으로 응답하지 않습니다. 잠시 후 같은 명령을 다시 실행하세요") from None
    except APIError:
        raise SystemExit("Gemini 요청이 거절됐습니다. API 키와 모델 설정을 확인하세요") from None
    print(json.dumps(result["rag_input"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
