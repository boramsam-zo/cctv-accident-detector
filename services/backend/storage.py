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
        if not bucket:
            raise ValueError("S3_BUCKET is required")
        self.bucket = bucket
        self.client = client or boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)

    def key_from_ref(self, ref: str) -> str:
        if ref.startswith("s3://"):
            parsed = urlparse(ref)
            if parsed.netloc != self.bucket:
                raise ValueError("unexpected_s3_bucket")
            return parsed.path.lstrip("/")
        if "://" in ref:
            raise ValueError("unsupported_asset_url")
        return ref

    def put_video(self, key: str, stream, max_bytes: int) -> StoredObject:
        data = stream.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("empty_or_oversized_video")
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ValueError("unsupported_video_content")
        digest = hashlib.sha256(data).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="video/mp4")
        return StoredObject(key, digest, len(data))

    def get_bytes(self, key: str, max_bytes: int) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        if obj.get("ContentLength", 0) > max_bytes:
            raise ValueError("asset_too_large")
        data = obj["Body"].read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("asset_too_large")
        return data

    def get_json(self, key: str, max_bytes: int = 2_000_000) -> dict:
        return json.loads(self.get_bytes(key, max_bytes))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise

    def url(self, key: str, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )
