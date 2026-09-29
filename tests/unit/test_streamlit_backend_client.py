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
