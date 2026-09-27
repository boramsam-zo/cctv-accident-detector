import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    s3_bucket: str
    s3_endpoint_url: str | None
    aws_region: str
    pod_worker_token: str
    gemini_api_key: str
    gemini_model: str
    app_api_key: str
    analysis_profile_id: str
    max_upload_bytes: int
    max_gemini_clip_bytes: int
    worker_lease_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./backend.db"),
            s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            aws_region=os.getenv("AWS_REGION", "ap-northeast-2"),
            pod_worker_token=os.getenv("POD_WORKER_TOKEN", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            app_api_key=os.getenv("APP_API_KEY", ""),
            analysis_profile_id=os.getenv("ANALYSIS_PROFILE_ID", "received-yolo-x3ds-v1"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))),
            max_gemini_clip_bytes=int(os.getenv("MAX_GEMINI_CLIP_BYTES", str(18 * 1024 * 1024))),
            worker_lease_seconds=int(os.getenv("WORKER_LEASE_SECONDS", "60")),
        )
