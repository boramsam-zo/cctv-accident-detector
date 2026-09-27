"""Preview the VLM-to-RAG JSON with a signed S3 clip and image.

Set GEMINI_API_KEY, CLIP_PRESIGNED_URL and IMAGE_PRESIGNED_URL in the shell.
Signed URLs and media are read in memory and are never printed or saved.
"""

import json
import os
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from google.genai.errors import APIError, ServerError

from services.backend.gemini_vlm import GeminiVLM


MAX_MEDIA_BYTES = 18 * 1024 * 1024


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
    key = os.getenv("GEMINI_API_KEY")
    clip_url = os.getenv("CLIP_PRESIGNED_URL")
    image_url = os.getenv("IMAGE_PRESIGNED_URL")
    if not key or not clip_url or not image_url:
        raise SystemExit("GEMINI_API_KEY, CLIP_PRESIGNED_URL, IMAGE_PRESIGNED_URL을 설정하세요")
    clip = fetch_signed_s3(clip_url, MAX_MEDIA_BYTES, "clip")
    image = fetch_signed_s3(image_url, MAX_MEDIA_BYTES - len(clip), "image")
    if len(clip) < 12 or clip[4:8] != b"ftyp":
        raise SystemExit("clip: MP4 파일 내용이 아닙니다")
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit("image: PNG 파일 내용이 아닙니다")
    candidate = os.getenv("CANDIDATE_TIME_S")
    event = {"event_id": os.getenv("EVENT_ID", "event_000"),
             "camera_id": os.getenv("CAMERA_ID") or None,
             "candidate_time_s": float(candidate) if candidate else None,
             "start_seconds": None, "end_seconds": None,
             "object_observations": []}
    try:
        result = GeminiVLM(key, os.getenv("GEMINI_MODEL", "gemini-3.6-flash")).analyze(
            event, [("sample-clip", "video/mp4", clip), ("sample-frame", "image/png", image)])
    except ServerError:
        raise SystemExit("Gemini 서비스가 일시적으로 응답하지 않습니다. 잠시 후 같은 명령을 다시 실행하세요") from None
    except APIError:
        raise SystemExit("Gemini 요청이 거절됐습니다. API 키와 모델 설정을 확인하세요") from None
    print(json.dumps(result["rag_input"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
