import hashlib
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.backend.app import create_app
from services.backend.gemini_vlm import GeminiVLM
from services.backend.settings import Settings
from services.backend.storage import StoredObject


class FakeStorage:
    bucket = "test-bucket"

    def __init__(self):
        self.objects = {}

    def put_video(self, key, stream, max_bytes):
        data = stream.read()
        self.objects[key] = data
        return StoredObject(key, hashlib.sha256(data).hexdigest(), len(data))

    def get_bytes(self, key, max_bytes):
        data = self.objects[key]
        if len(data) > max_bytes:
            raise ValueError("asset_too_large")
        return data

    def exists(self, key):
        return key in self.objects

    def key_from_ref(self, ref):
        if ref.startswith("s3://test-bucket/"):
            return ref.removeprefix("s3://test-bucket/")
        return ref

    def url(self, key):
        return f"https://example.invalid/{key}"


class FakeGemini:
    def __init__(self):
        self.calls = 0

    def analyze(self, event, media):
        self.calls += 1
        return {"status": "completed", "summary": "차량의 움직임을 확인했습니다.",
                "rag_input": {"event_id": event["event_id"],
                              "candidate_time_s": event["candidate_time_s"],
                              "description": "차량의 움직임을 확인했습니다.",
                              "scene_conditions": {"day_time": "day", "weather": None},
                              "involved_objects": [{"type": "car", "count": 2}],
                              "accident_type": None, "lane_blocked": None,
                              "affected_person_visible": False, "fire_visible": False,
                              "operator_confirmed": False},
                "observations": [{"text": "차량이 보입니다.", "evidence_asset_ids": [media[0][0]],
                                  "source_times_seconds": [event["start_seconds"]]}],
                "uncertainties": ["접촉 여부는 확인이 필요합니다."],
                "provider_model": "fake", "prompt_version": "test"}


def put_json(storage, key, value):
    raw = json.dumps(value).encode()
    storage.objects[key] = raw
    return hashlib.sha256(raw).hexdigest()


def test_pod_partial_event_gemini_review_and_empty_run(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", s3_bucket="test-bucket",
        s3_endpoint_url=None, aws_region="ap-northeast-2", pod_worker_token="pod-token",
        gemini_api_key="test", gemini_model="fake", app_api_key="test",
        analysis_profile_id="profile-1", max_upload_bytes=1000,
        max_gemini_clip_bytes=1000, worker_lease_seconds=60,
    )
    storage, gemini = FakeStorage(), FakeGemini()
    app = create_app(settings, storage=storage, gemini=gemini, video_probe=lambda _: 10.0)
    client = TestClient(app)
    headers = {"Authorization": "Bearer test", "Idempotency-Key": "upload-1"}
    pod_headers = {"Authorization": "Bearer pod-token"}
    video = b"\x00\x00\x00\x18ftypmp42" + b"x" * 20
    upload = client.post("/api/v1/videos", files={"file": ("sample.mp4", video, "video/mp4")}, headers=headers)
    assert upload.status_code == 201, upload.text
    assert upload.headers["X-Request-ID"]
    assert upload.json()["duration_seconds"] == 10.0
    assert client.post("/api/v1/videos", files={"file": ("sample.mp4", video, "video/mp4")}, headers=headers).json() == upload.json()
    conflict = client.post("/api/v1/videos", files={"file": ("sample.mp4", video + b"changed", "video/mp4")}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    video_id = upload.json()["source_video_id"]
    assert client.get("/api/v1/videos", headers=headers).json()["items"][0]["source_video_id"] == video_id
    assert client.get("/api/v1/analysis-profiles", headers=headers).json()["items"][0]["analysis_profile_id"] == "profile-1"
    headers["Idempotency-Key"] = "job-1"
    job = client.post("/api/v1/jobs", json={"source_video_id": video_id, "analysis_profile_id": "profile-1"}, headers=headers)
    assert job.status_code == 202, job.text
    assert job.json()["detection_outcome"] == "pending"
    job_id, run_id = job.json()["job_id"], job.json()["run_id"]
    started = datetime.now(timezone.utc).isoformat()
    registration = {"pod_id": "pod-1", "worker_instance_id": "worker-1", "started_at": started,
                    "models": {"objects": {"family": "YOLO11s"}, "accident": {"family": "X3D-S"}}}
    assert client.post("/internal/v1/workers/register", json=registration, headers=pod_headers).status_code == 201
    heartbeat = {"status": "ready", "active_run_id": None, "sent_at": started}
    assert client.post("/internal/v1/workers/worker-1/heartbeat", json=heartbeat, headers=pod_headers).status_code == 200
    assignment = client.post("/internal/v1/workers/worker-1/claim", headers=pod_headers).json()["assignment"]
    assert assignment["run_id"] == run_id
    assert assignment["analysis_profile"]["analysis_mode"] == "file_realtime_1x"
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"] == "running"
    prefix = assignment["output_prefix"]
    clip_key, frame_key = prefix + "clip.mp4", prefix + "frame.jpg"
    storage.objects[clip_key], storage.objects[frame_key] = b"clip", b"frame"
    event_id = "event-1"
    manifest = {"schema_version": "service-draft-v0.2", "run_id": run_id, "event_id": event_id,
                "sequence_number": 1, "start_seconds": 2.0, "end_seconds": 4.0,
                "candidate_time_s": 3.0, "score": 0.8,
                "score_type": "max_window_score", "prediction_ids": ["pred-1"],
                "object_observations": [], "evidence": {
                    "clip_start_seconds": 1.0, "clip_end_seconds": 5.0,
                    "clip": {"key": clip_key, "sha256": hashlib.sha256(b"clip").hexdigest(), "mime_type": "video/mp4"},
                    "frames": [{"key": frame_key, "sha256": hashlib.sha256(b"frame").hexdigest(),
                                "mime_type": "image/jpeg", "source_time_seconds": 3.0}]}}
    manifest_key = prefix + "event.json"
    digest = put_json(storage, manifest_key, manifest)
    event_request = {"schema_version": "service-draft-v0.2", "event_id": event_id,
                     "sequence_number": 1, "worker_instance_id": "worker-1",
                     "start_seconds": 2.0, "end_seconds": 4.0, "candidate_time_s": 3.0,
                     "manifest_key": manifest_key,
                     "manifest_sha256": digest, "detected_at": started}
    missing_time = {key: value for key, value in event_request.items() if key != "candidate_time_s"}
    assert client.post(f"/internal/v1/runs/{run_id}/events",
                       json=missing_time, headers=pod_headers).status_code == 422
    mismatch = client.post(f"/internal/v1/runs/{run_id}/events",
                           json={**event_request, "candidate_time_s": 3.5}, headers=pod_headers)
    assert mismatch.status_code == 409
    event = client.post(f"/internal/v1/runs/{run_id}/events", json=event_request, headers=pod_headers)
    assert event.status_code == 201, event.text
    assert client.post(f"/internal/v1/runs/{run_id}/events", json=event_request, headers=pod_headers).status_code == 201
    assert len(client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["candidates"]) == 1
    assert app.state.get_enrichment_worker().tick()
    assert gemini.calls == 1
    final_manifest = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                      "coverage": {"requested_start_seconds": 0, "requested_end_seconds": 10,
                                   "scheduled_windows": 1, "predicted_windows": 1,
                                   "unclassified_windows": 0, "pending_windows": 0, "unknown_ranges": []},
                      "models": {}, "errors": []}
    final_key = prefix + "final.json"
    final_digest = put_json(storage, final_key, final_manifest)
    complete = client.post(f"/internal/v1/runs/{run_id}/complete", json={
        "worker_instance_id": "worker-1", "manifest_key": final_key,
        "manifest_sha256": final_digest}, headers=pod_headers)
    assert complete.status_code == 200, complete.text
    result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "completed"
    event_result = result["candidates"][0]
    assert event_result["vlm"]["summary"] == "차량의 움직임을 확인했습니다."
    assert event_result["rag_input"]["operator_confirmed"] is False
    assert event_result["rag_input"]["event_id"] == event_id
    assert event_result["rag_input"]["candidate_time_s"] == 3.0
    assert "camera_id" not in event_result["rag_input"]
    assert event_result["retrieval"]["status"] == "insufficient_evidence"
    asset_id = event_result["evidence"]["clip_asset_id"]
    assert client.get(f"/api/v1/assets/{asset_id}/url", headers=headers).json()["content_type"] == "video/mp4"
    review = {"run_id": run_id, "report_revision": 1, "decision": "uncertain",
              "note": "원본 확인 필요", "expected_review_revision": 0}
    headers["Idempotency-Key"] = "review-1"
    assert client.post(f"/api/v1/events/{event_id}/reviews", json=review, headers=headers).status_code == 201
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["candidates"][0]["human_review"]["status"] == "uncertain"
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["candidates"][0]["rag_input"]["operator_confirmed"] is False
    assert client.get(f"/api/v1/events/{event_id}/reviews", headers=headers).json()["items"][0]["decision"] == "uncertain"
    headers["Idempotency-Key"] = "review-2"
    assert client.post(f"/api/v1/events/{event_id}/reviews", json=review, headers=headers).json()["error"]["code"] == "REVIEW_REVISION_CONFLICT"
    headers["Idempotency-Key"] = "review-3"
    confirmed = {**review, "decision": "confirmed_accident", "expected_review_revision": 1}
    assert client.post(f"/api/v1/events/{event_id}/reviews", json=confirmed, headers=headers).status_code == 201
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["candidates"][0]["rag_input"]["operator_confirmed"] is False
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["candidates"][0]["human_review"]["status"] == "confirmed_accident"

    headers["Idempotency-Key"] = "job-empty"
    second = client.post("/api/v1/jobs", json={"source_video_id": video_id, "analysis_profile_id": "profile-1"}, headers=headers).json()
    heartbeat["active_run_id"] = None
    client.post("/internal/v1/workers/worker-1/heartbeat", json=heartbeat, headers=pod_headers)
    second_assignment = client.post("/internal/v1/workers/worker-1/claim", headers=pod_headers).json()["assignment"]
    assert second_assignment["run_id"] == second["run_id"]
    empty_key = second_assignment["output_prefix"] + "final.json"
    empty_digest = put_json(storage, empty_key, {**final_manifest, "run_id": second["run_id"]})
    complete_empty = client.post(f"/internal/v1/runs/{second['run_id']}/complete", json={
        "worker_instance_id": "worker-1", "manifest_key": empty_key,
        "manifest_sha256": empty_digest}, headers=pod_headers)
    assert complete_empty.status_code == 200, complete_empty.text
    empty_result = client.get(f"/api/v1/jobs/{second['job_id']}", headers=headers).json()
    assert empty_result["status"] == "completed"
    assert empty_result["detection_outcome"] == "no_candidates"
    assert gemini.calls == 1


def test_gemini_rejects_unknown_evidence_id():
    class FakeModels:
        def generate_content(self, **kwargs):
            class Response:
                text = json.dumps({"description": "관찰", "operator_confirmed": None,
                    "scene_conditions": {"day_time": None, "weather": None},
                    "involved_objects": [], "accident_type": None, "lane_blocked": None,
                    "affected_person_visible": None, "fire_visible": None,
                    "observations": [
                    {"text": "차량", "evidence_asset_ids": ["unknown"], "source_times_seconds": [2.0]}],
                    "uncertainties": []})
            return Response()

    class FakeClient:
        models = FakeModels()

    vlm = GeminiVLM("", "fake", FakeClient())
    try:
        vlm.analyze({"event_id": "e1", "candidate_time_s": 2.0,
                     "start_seconds": 1, "end_seconds": 3},
                    [("asset-1", "image/jpeg", b"frame")])
    except ValueError as exc:
        assert str(exc) == "invalid_evidence_asset_id"
    else:
        raise AssertionError("unknown evidence ID was accepted")


def test_gemini_builds_rag_input_without_inventing_metadata():
    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["config"]["response_schema"].__name__ == "GeminiResult"
            class Response:
                text = json.dumps({"description": "차량 두 대가 가까워집니다.",
                    "operator_confirmed": False,
                    "scene_conditions": {"day_time": "day", "weather": None},
                    "involved_objects": [{"type": "car", "count": 2}],
                    "accident_type": None, "lane_blocked": None,
                    "affected_person_visible": False, "fire_visible": False,
                    "observations": [{"text": "차량 두 대", "evidence_asset_ids": ["frame-1"],
                                      "source_times_seconds": []}], "uncertainties": ["접촉은 확인되지 않습니다."]})
            return Response()

    class FakeClient:
        models = FakeModels()

    vlm = GeminiVLM("", "fake", FakeClient())
    result = vlm.analyze({"event_id": "event_000",
                          "candidate_time_s": 2.0, "start_seconds": 1.0, "end_seconds": 3.0},
                         [("frame-1", "image/png", b"frame")])
    assert result["rag_input"] == {
        "event_id": "event_000", "candidate_time_s": 2.0,
        "description": "차량 두 대가 가까워집니다.",
        "scene_conditions": {"day_time": "day", "weather": None},
        "involved_objects": [{"type": "car", "count": 2}],
        "accident_type": None, "lane_blocked": None,
        "affected_person_visible": False, "fire_visible": False,
        "operator_confirmed": False}
