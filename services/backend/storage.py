import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    size: int


class S3Storage:
    def __init__(self, bucket: str, client=None, *, endpoint_url=None, region_name=None):
        """버킷 설정을 확인하고 S3 클라이언트를 준비한다."""
        if not bucket:
            raise ValueError("S3_BUCKET is required")
        self.bucket = bucket
        self.client = client or boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)

    def key_from_ref(self, ref: str) -> str:
        """같은 버킷의 S3 URI 또는 객체 키를 내부 객체 키로 변환한다."""
        if ref.startswith("s3://"):
            parsed = urlparse(ref)
            if parsed.netloc != self.bucket:
                raise ValueError("unexpected_s3_bucket")
            return parsed.path.lstrip("/")
        if "://" in ref:
            raise ValueError("unsupported_asset_url")
        return ref

    def put_video(self, key: str, stream, max_bytes: int) -> StoredObject:
        """MP4 형식과 크기를 확인해 S3에 저장하고 해시·크기를 반환한다."""
        data = stream.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("empty_or_oversized_video")
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ValueError("unsupported_video_content")
        digest = hashlib.sha256(data).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="video/mp4")
        return StoredObject(key, digest, len(data))

    def put_model_weight(self, key: str, stream, max_bytes: int) -> StoredObject:
        """가중치 파일을 크기 제한 내에서 해시 계산 후 S3에 스트리밍 업로드한다."""
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("empty_or_oversized_model_weight")
            digest.update(chunk)
        if size == 0:
            raise ValueError("empty_or_oversized_model_weight")
        stream.seek(0)
        self.client.upload_fileobj(
            stream, self.bucket, key,
            ExtraArgs={"ContentType": "application/octet-stream"},
        )
        return StoredObject(key, digest.hexdigest(), size)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get_bytes(self, key: str, max_bytes: int) -> bytes:
        """최대 크기를 넘지 않는 S3 객체를 바이트로 읽는다."""
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        if obj.get("ContentLength", 0) > max_bytes:
            raise ValueError("asset_too_large")
        data = obj["Body"].read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("asset_too_large")
        return data

    def get_json(self, key: str, max_bytes: int = 2_000_000) -> dict:
        """크기 제한을 적용해 S3의 JSON 객체를 읽고 파싱한다."""
        return json.loads(self.get_bytes(key, max_bytes))

    def exists(self, key: str) -> bool:
        """S3 객체의 존재 여부를 확인하고 다른 저장소 오류는 전달한다."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise

    def url(self, key: str, expires: int = 300) -> str:
        """S3 객체를 임시로 내려받을 수 있는 서명 URL을 발급한다."""
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )
