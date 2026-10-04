"""Server-side HTTP client for the FastAPI service."""

import os
from typing import Any

import httpx


class BackendError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None,
                 code: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class BackendClient:
    def __init__(self, base_url: str, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport

    @classmethod
    def from_env(cls) -> "BackendClient | None":
        url, key = os.getenv("BACKEND_API_URL"), os.getenv("APP_API_KEY")
        return cls(url, key) if url and key else None

    def request(self, method: str, path: str, *, idempotency_key: str | None = None,
                **kwargs: Any) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with httpx.Client(base_url=self.base_url, transport=self.transport,
                              timeout=httpx.Timeout(120, connect=5)) as client:
                response = client.request(method, path, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise BackendError("백엔드에 연결할 수 없습니다.", retryable=True) from exc
        if response.is_error:
            try:
                error = response.json()["error"]
            except (ValueError, KeyError, TypeError):
                error = {}
            raise BackendError(error.get("message") or "백엔드 요청이 실패했습니다.",
                               status_code=response.status_code, code=error.get("code"),
                               retryable=error.get("retryable", response.status_code >= 500))
        return response.json()

    def health(self) -> dict:
        return self.request("GET", "/health")

    def rag_status(self) -> dict:
        return self.request("GET", "/api/v1/rag/status")

    def list_videos(self) -> dict:
        return self.request("GET", "/api/v1/videos", params={"limit": 100})

    def all_videos(self) -> list[dict]:
        return self._all_pages("/api/v1/videos")

    def upload_video(self, name: str, data: bytes, camera_id: str | None, key: str) -> dict:
        return self.request("POST", "/api/v1/videos", idempotency_key=key,
                            files={"file": (name, data, "video/mp4")},
                            data={"camera_id": camera_id} if camera_id else {})

    def analysis_profile(self) -> str:
        items = self.analysis_profiles()
        profile = next((item for item in items if item["is_default"] and item["enabled"]), None)
        if profile is None:
            raise BackendError("사용 가능한 분석 프로필이 없습니다.")
        return profile["analysis_profile_id"]

    def analysis_profiles(self) -> list[dict]:
        return self.request("GET", "/api/v1/analysis-profiles")["items"]

    def create_analysis_profile(self, *, display_name: str, description: str,
                                accident_family: str, object_family: str,
                                accident_name: str, accident_data: bytes,
                                object_name: str, object_data: bytes) -> dict:
        return self.request(
            "POST", "/api/v1/analysis-profiles", timeout=600,
            data={"display_name": display_name, "description": description,
                  "accident_family": accident_family, "object_family": object_family},
            files={
                "accident_weights": (accident_name, accident_data, "application/octet-stream"),
                "object_weights": (object_name, object_data, "application/octet-stream"),
            },
        )

    def vlm_options(self) -> dict:
        return self.request("GET", "/api/v1/vlm-options")

    def check_vlm(self, model: str) -> dict:
        return self.request("POST", "/api/v1/vlm-options/check", json={"model": model})

    def create_job(self, video_id: str, profile_id: str, key: str, *,
                   vlm_model: str | None = None, vlm_prompt: str = "",
                   vlm_prompt_mode: str = "prepend", defer_vlm: bool = False) -> dict:
        payload = {"source_video_id": video_id, "analysis_profile_id": profile_id}
        if defer_vlm:
            payload["defer_vlm"] = True
        if vlm_model:
            payload["vlm"] = {"model": vlm_model, "prompt": vlm_prompt,
                              "prompt_mode": vlm_prompt_mode}
        return self.request("POST", "/api/v1/jobs", idempotency_key=key,
                            json=payload)

    def list_jobs(self, video_id: str | None = None) -> dict:
        params = {"limit": 100}
        if video_id:
            params["source_video_id"] = video_id
        return self.request("GET", "/api/v1/jobs", params=params)

    def all_jobs(self) -> list[dict]:
        return self._all_pages("/api/v1/jobs")

    def _all_pages(self, path: str) -> list[dict]:
        items: list[dict] = []
        cursor = None
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = self.request("GET", path, params=params)
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def get_job(self, job_id: str) -> dict:
        return self.request("GET", f"/api/v1/jobs/{job_id}")

    def start_vlm(self, job_id: str, key: str) -> dict:
        return self.request("POST", f"/api/v1/jobs/{job_id}/vlm",
                            idempotency_key=key)

    def rerun_job(self, job_id: str, profile_id: str, key: str) -> dict:
        return self.request("POST", f"/api/v1/jobs/{job_id}/runs", idempotency_key=key,
                            json={"analysis_profile_id": profile_id})

    def asset_url(self, asset_id: str) -> dict:
        return self.request("GET", f"/api/v1/assets/{asset_id}/url")

    def list_reviews(self, event_id: str) -> dict:
        return self.request("GET", f"/api/v1/events/{event_id}/reviews", params={"limit": 1})

    def create_review(self, event_id: str, payload: dict, key: str) -> dict:
        return self.request("POST", f"/api/v1/events/{event_id}/reviews",
                            idempotency_key=key, json=payload)
