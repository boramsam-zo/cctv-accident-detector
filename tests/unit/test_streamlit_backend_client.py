import json

import httpx
import pytest

from apps.streamlit.backend_client import BackendClient, BackendError


def test_client_passes_auth_idempotency_and_contract_fields():
    """클라이언트가 인증·멱등성 헤더와 작업 생성 계약 필드를 전달하는지 확인한다."""
    seen = []

    def handle(request):
        """분석 프로필과 작업 생성 요청을 기록하고 테스트 응답을 반환한다."""
        seen.append(request)
        if request.url.path == "/api/v1/analysis-profiles":
            return httpx.Response(200, json={"items": [
                {"analysis_profile_id": "profile-1", "enabled": True, "is_default": True}
            ]})
        if request.url.path == "/api/v1/jobs":
            return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        raise AssertionError(request.url.path)

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))
    profile = client.analysis_profile()
    job = client.create_job("video-1", profile, "request-1")

    assert job["job_id"] == "job-1"
    assert seen[0].headers["Authorization"] == "Bearer team-token"
    assert seen[1].headers["Idempotency-Key"] == "request-1"
    assert seen[1].read() == b'{"source_video_id":"video-1","analysis_profile_id":"profile-1"}'


def test_client_surfaces_review_revision_conflict():
    """검토 버전 충돌 응답을 호출자가 구분할 수 있는 예외로 전달한다."""
    def handle(request):
        """검토 버전 충돌에 해당하는 HTTP 409 응답을 반환한다."""
        return httpx.Response(409, json={"error": {
            "code": "REVIEW_REVISION_CONFLICT", "message": "Review revision changed",
            "retryable": False
        }})

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))
    with pytest.raises(BackendError) as caught:
        client.create_review("event-1", {"expected_review_revision": 0}, "request-2")
    assert caught.value.status_code == 409
    assert caught.value.code == "REVIEW_REVISION_CONFLICT"


def test_client_loads_vlm_options_and_sends_job_overrides():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/api/v1/vlm-options":
            return httpx.Response(200, json={
                "models": ["gemini-a", "gemini-b"],
                "default_model": "gemini-a",
                "prompt_default": "",
                "prompt_modes": ["prepend", "replace"],
                "default_prompt_mode": "prepend",
            })
        if request.url.path == "/api/v1/vlm-options/check":
            return httpx.Response(200, json={
                "available": True, "model": "gemini-b", "latency_ms": 25,
                "response_preview": "OK", "error_code": None,
            })
        return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))

    assert client.vlm_options()["models"] == ["gemini-a", "gemini-b"]
    assert client.check_vlm("gemini-b")["available"] is True
    client.create_job("video-1", "profile-1", "request-3", vlm_model="gemini-b",
                      vlm_prompt="차량 수를 세세요.", vlm_prompt_mode="replace")

    assert json.loads(seen[2].read()) == {
        "source_video_id": "video-1",
        "analysis_profile_id": "profile-1",
        "vlm": {"model": "gemini-b", "prompt": "차량 수를 세세요.",
                "prompt_mode": "replace"},
    }


def test_client_uploads_both_model_weights_for_profile_registration():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(201, json={"analysis_profile_id": "profile-new"})

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))
    result = client.create_analysis_profile(
        display_name="custom", description="weights", accident_family="X3D-S",
        object_family="YOLO11", accident_name="x3d.pt", accident_data=b"x3d",
        object_name="yolo.pt", object_data=b"yolo",
    )

    body = seen[0].read()
    assert result["analysis_profile_id"] == "profile-new"
    assert b'name="accident_weights"; filename="x3d.pt"' in body
    assert b'name="object_weights"; filename="yolo.pt"' in body
    assert b'name="display_name"' in body and b"custom" in body


def test_client_can_defer_and_manually_start_vlm():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))
    client.create_job("video-1", "profile-1", "create-1", defer_vlm=True)
    client.start_vlm("job-1", "vlm-1")

    assert json.loads(seen[0].read())["defer_vlm"] is True
    assert seen[1].url.path == "/api/v1/jobs/job-1/vlm"
    assert seen[1].headers["Idempotency-Key"] == "vlm-1"
