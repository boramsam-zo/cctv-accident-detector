"""로컬 clip 미리보기 스크립트의 입력 선택과 용량 검사를 확인한다."""

import json
from unittest.mock import patch

import pytest

from scripts import preview_gemini_rag as preview


def test_local_clip_uses_ignored_env_and_needs_no_frame(tmp_path, monkeypatch, capsys):
    """로컬 clip 하나와 .env 키만으로 현재 Gemini 경로를 호출하는지 확인한다."""
    monkeypatch.setattr(preview, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("CLIP_FILE", raising=False)
    monkeypatch.delenv("IMAGE_FILE", raising=False)
    monkeypatch.delenv("CLIP_PRESIGNED_URL", raising=False)
    monkeypatch.delenv("IMAGE_PRESIGNED_URL", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\nGEMINI_MODEL=test-model\n")
    local = tmp_path / ".local"
    local.mkdir()
    clip = b"\x00\x00\x00\x18ftypmp42" + b"video"
    (local / "clip.mp4").write_bytes(clip)

    with patch.object(preview, "GeminiVLM") as vlm:
        vlm.return_value.analyze.return_value = {"rag_input": {"description": "검사 결과"}}
        preview.main()

    assert vlm.call_args.args == ("test-key", "test-model")
    assert vlm.return_value.analyze.call_args.args[1] == [("sample-clip", "video/mp4", clip)]
    assert json.loads(capsys.readouterr().out) == {"description": "검사 결과"}


def test_local_media_limit_is_enforced(tmp_path):
    """로컬 clip이 허용 크기를 넘으면 파일 읽기를 거부한다."""
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"12345")
    with pytest.raises(ValueError, match="상한을 초과"):
        preview.read_local(clip, 4, "clip")
