"""S3 경계에서 실제 boto3 요청과 객체 검증 규칙을 확인한다."""

import hashlib
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws

from services.backend.storage import S3Storage


@pytest.fixture
def storage(monkeypatch):
    """실제 AWS 자격 증명 대신 격리된 Moto 버킷을 제공한다."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="backend-unit-test")
        yield S3Storage("backend-unit-test", client=client)


def test_video_round_trip_and_signed_url(storage):
    """MP4 저장·조회·해시·서명 URL 발급이 Moto S3에서 동작하는지 확인한다."""
    video = b"\x00\x00\x00\x18ftypmp42" + b"video-bytes"

    stored = storage.put_video("videos/one/original.mp4", BytesIO(video), len(video))

    assert stored.sha256 == hashlib.sha256(video).hexdigest()
    assert stored.size == len(video)
    assert storage.exists(stored.key)
    assert storage.get_bytes(stored.key, len(video)) == video
    assert storage.client.head_object(Bucket=storage.bucket, Key=stored.key)["ContentType"] == "video/mp4"
    signed = urlparse(storage.url(stored.key))
    assert signed.path.endswith(stored.key)
    assert {"Signature", "X-Amz-Signature"} & parse_qs(signed.query).keys()


@pytest.mark.parametrize("payload,limit,error", [
    (b"", 100, "empty_or_oversized_video"),
    (b"\x00\x00\x00\x18ftypmp42extra", 10, "empty_or_oversized_video"),
    (b"not-an-mp4-file", 100, "unsupported_video_content"),
])
def test_video_rejects_invalid_content_without_upload(storage, payload, limit, error):
    """빈 파일·용량 초과·비 MP4 파일은 S3에 올리지 않는지 확인한다."""
    with pytest.raises(ValueError, match=error):
        storage.put_video("videos/invalid.mp4", BytesIO(payload), limit)
    assert not storage.exists("videos/invalid.mp4")


def test_read_limit_and_bucket_boundary(storage):
    """다운로드 크기와 S3 버킷·URL 경계를 지키는지 확인한다."""
    storage.client.put_object(Bucket=storage.bucket, Key="evidence/frame.png", Body=b"image")
    assert storage.key_from_ref("s3://backend-unit-test/evidence/frame.png") == "evidence/frame.png"
    with pytest.raises(ValueError, match="asset_too_large"):
        storage.get_bytes("evidence/frame.png", 4)
    with pytest.raises(ValueError, match="unexpected_s3_bucket"):
        storage.key_from_ref("s3://other-bucket/evidence/frame.png")
    with pytest.raises(ValueError, match="unsupported_asset_url"):
        storage.key_from_ref("https://example.com/evidence/frame.png")
