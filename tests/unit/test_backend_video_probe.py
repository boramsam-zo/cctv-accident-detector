"""업로드된 MP4의 메타데이터 검사 경계 조건을 확인한다."""

import json
import subprocess
from unittest.mock import patch

import pytest

from services.backend.video_probe import probe_mp4


def test_video_probe_reads_uploaded_bytes_and_duration():
    """ffprobe에 업로드 바이트를 전달하고 영상 길이를 읽는지 확인한다."""
    def ffprobe(command, **kwargs):
        """임시 파일 내용을 검사한 뒤 영상 메타데이터를 대신 반환한다."""
        assert command[0] == "ffprobe"
        with open(command[-1], "rb") as source:
            assert source.read() == b"uploaded-video"
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"streams": [{"codec_type": "video"}],
                                     "format": {"duration": "12.5"}}), "")

    with patch("services.backend.video_probe.subprocess.run", side_effect=ffprobe):
        assert probe_mp4(b"uploaded-video") == 12.5


@pytest.mark.parametrize("returncode,metadata,error", [
    (1, {}, "invalid_video"),
    (0, {"streams": [{"codec_type": "audio"}], "format": {"duration": "12"}}, "no_video_stream"),
    (0, {"streams": [{"codec_type": "video"}], "format": {"duration": "0"}}, "invalid_duration"),
])
def test_video_probe_rejects_unusable_media(returncode, metadata, error):
    """깨진 파일·영상 스트림 누락·길이 0인 파일을 거부하는지 확인한다."""
    completed = subprocess.CompletedProcess(["ffprobe"], returncode, json.dumps(metadata), "")
    with patch("services.backend.video_probe.subprocess.run", return_value=completed):
        with pytest.raises(ValueError, match=error):
            probe_mp4(b"uploaded-video")
