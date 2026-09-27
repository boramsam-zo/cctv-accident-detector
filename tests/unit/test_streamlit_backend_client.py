import httpx
import pytest

from apps.streamlit.backend_client import BackendClient, BackendError


def test_client_passes_auth_idempotency_and_contract_fields():
    seen = []

    def handle(request):
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
    def handle(request):
        return httpx.Response(409, json={"error": {
            "code": "REVIEW_REVISION_CONFLICT", "message": "Review revision changed",
            "retryable": False
        }})

    client = BackendClient("http://backend.test", "team-token", transport=httpx.MockTransport(handle))
    with pytest.raises(BackendError) as caught:
        client.create_review("event-1", {"expected_review_revision": 0}, "request-2")
    assert caught.value.status_code == 409
    assert caught.value.code == "REVIEW_REVISION_CONFLICT"
