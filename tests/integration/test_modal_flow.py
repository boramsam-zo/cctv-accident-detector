"""Exercise the Modal-backed upload, inference, S3, and Gemini flow."""

import hashlib
import json

from fastapi.testclient import TestClient

from services.backend.app import create_app
from services.backend.settings import Settings
from services.backend.storage import StoredObject


class MemoryStorage:
    bucket = "test-bucket"

    def __init__(self):
        """Hold S3 objects in memory while retaining the production storage contract."""
        self.objects = {}

    def put_video(self, key, stream, max_bytes):
        """Save a test upload and its digest."""
        data = stream.read(max_bytes + 1)
        self.objects[key] = data
        return StoredObject(key, hashlib.sha256(data).hexdigest(), len(data))

    def get_bytes(self, key, max_bytes):
        """Read one object subject to the backend's size limit."""
        data = self.objects[key]
        if len(data) > max_bytes:
            raise ValueError("asset_too_large")
        return data

    def exists(self, key):
        """Report whether an evidence object was written."""
        return key in self.objects

    def key_from_ref(self, ref):
        """Convert a same-bucket URI into an object key."""
        return ref.removeprefix("s3://test-bucket/")

    def url(self, key):
        """Provide an inspectable evidence URL to the API."""
        return f"https://example.invalid/{key}"


class FakeGateway:
    def __init__(self, storage, candidates=True, corrupt=False):
        """Prepare a deterministic Modal response with real manifest bytes."""
        self.storage, self.candidates, self.corrupt = storage, candidates, corrupt
        self.assignment = None

    def _json(self, key, payload):
        """Store a manifest and return its digest reference."""
        blob = json.dumps(payload).encode()
        self.storage.objects[key] = blob
        return {"manifest_key": key, "manifest_sha256": hashlib.sha256(blob).hexdigest()}

    def spawn(self, assignment):
        """Record the backend assignment and return a fake Modal call ID."""
        self.assignment = assignment
        return "fc-test-1"

    def poll(self, call_id):
        """Create S3 evidence and return the completed Modal call payload."""
        assert call_id == "fc-test-1"
        a = self.assignment
        prefix, run_id = a["output_prefix"], a["run_id"]
        events = []
        if self.candidates:
            event_id = f"{run_id}-001"
            clip_key = prefix + "events/clip.mp4"
            frame_key = prefix + "events/frame.jpg"
            self.storage.objects[clip_key] = b"clip"
            self.storage.objects[frame_key] = b"frame"
            manifest = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                        "event_id": event_id, "sequence_number": 1,
                        "start_seconds": 2.0, "end_seconds": 4.0, "candidate_time_s": 3.0,
                        "object_observations": [], "evidence": {
                            "clip_start_seconds": 1.0, "clip_end_seconds": 5.0,
                            "clip": {"key": clip_key, "sha256": hashlib.sha256(b"clip").hexdigest(),
                                     "mime_type": "video/mp4"},
                            "frames": [{"key": frame_key, "sha256": hashlib.sha256(b"frame").hexdigest(),
                                        "mime_type": "image/jpeg", "source_time_seconds": 3.0}]}}
            events.append(self._json(prefix + "events/manifest.json", manifest))
            if self.corrupt:
                self.storage.objects[clip_key] = b"changed"
        final = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                 "coverage": {"requested_start_seconds": 0.0, "requested_end_seconds": 10.0,
                              "scheduled_windows": 1, "predicted_windows": 1,
                              "unclassified_windows": 0, "pending_windows": 0, "unknown_ranges": []},
                 "models": {}, "errors": []}
        ref = self._json(prefix + "final.json", final)
        return {"schema_version": "modal-inference-v1", "run_id": run_id,
                "events": events, "final_manifest_key": ref["manifest_key"],
                "final_manifest_sha256": ref["manifest_sha256"]}


class FakeGemini:
    def analyze(self, event, media):
        """Return a valid enrichment payload for the registered evidence."""
        return {"status": "completed", "summary": "차량이 보입니다.",
                "observations": [], "uncertainties": [],
                "rag_input": {"event_id": event["event_id"],
                              "candidate_time_s": event["candidate_time_s"],
                              "description": "차량이 보입니다.",
                              "scene_conditions": {"day_time": "day", "weather": None},
                              "involved_objects": [], "accident_type": None,
                              "lane_blocked": None, "affected_person_visible": False,
                              "fire_visible": False, "operator_confirmed": None}}


def make_test_app(tmp_path, candidates=True, corrupt=False, key_prefix=""):
    """Create an API with isolated DB, S3, Modal, and Gemini dependencies."""
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'modal.db'}",
                        s3_bucket="test-bucket", s3_endpoint_url=None,
                        aws_region="ap-northeast-2", pod_worker_token="unused",
                        gemini_api_key="test", gemini_model="fake", app_api_key="test",
                        analysis_profile_id="profile-1", max_upload_bytes=1000,
                        max_gemini_clip_bytes=1000, worker_lease_seconds=60,
                        s3_key_prefix=key_prefix)
    storage = MemoryStorage()
    gateway = FakeGateway(storage, candidates=candidates, corrupt=corrupt)
    app = create_app(settings, storage=storage, gemini=FakeGemini(),
                     video_probe=lambda _: 10.0, modal_gateway=gateway)
    return app, gateway


def submit_video_job(client):
    """Upload one MP4 and request asynchronous analysis through public APIs."""
    headers = {"Authorization": "Bearer test", "Idempotency-Key": "upload-1"}
    video = b"\x00\x00\x00\x18ftypmp42" + b"x" * 20
    uploaded = client.post("/api/v1/videos", files={"file": ("sample.mp4", video, "video/mp4")},
                           headers=headers)
    assert uploaded.status_code == 201
    headers["Idempotency-Key"] = "job-1"
    response = client.post("/api/v1/jobs", json={"source_video_id": uploaded.json()["source_video_id"],
                                                  "analysis_profile_id": "profile-1"}, headers=headers)
    assert response.status_code == 202
    return response.json()["job_id"], headers


def test_modal_candidate_flow_reaches_gemini_and_public_asset_api(tmp_path):
    """Check uploaded video through Modal evidence, Gemini, and UI-facing APIs."""
    app, gateway = make_test_app(tmp_path)
    client = TestClient(app)
    job_id, headers = submit_video_job(client)
    assert app.state.get_modal_worker().tick()
    assert gateway.assignment["input_object"]["bucket"] == "test-bucket"
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"] == "running"
    assert app.state.get_modal_worker().tick()
    assert app.state.get_enrichment_worker().tick()
    result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "completed"
    assert result["detection_outcome"] == "candidates_found"
    assert result["candidates"][0]["rag_input"]["candidate_time_s"] == 3.0
    clip_id = result["candidates"][0]["evidence"]["clip_asset_id"]
    assert client.get(f"/api/v1/assets/{clip_id}/url", headers=headers).status_code == 200


def test_modal_no_candidate_run_skips_gemini(tmp_path):
    """Complete a fully classified run without creating candidate evidence."""
    app, _ = make_test_app(tmp_path, candidates=False)
    client = TestClient(app)
    job_id, headers = submit_video_job(client)
    assert app.state.get_modal_worker().tick()
    assert app.state.get_modal_worker().tick()
    assert not app.state.get_enrichment_worker().tick()
    result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "completed"
    assert result["detection_outcome"] == "no_candidates"


def test_modal_rejects_modified_s3_evidence(tmp_path):
    """Fail a run when Modal's evidence digest differs from stored bytes."""
    app, _ = make_test_app(tmp_path, corrupt=True)
    client = TestClient(app)
    job_id, headers = submit_video_job(client)
    assert app.state.get_modal_worker().tick()
    assert app.state.get_modal_worker().tick()
    result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "ValueError"


def test_modal_uses_development_prefix_in_shared_bucket(tmp_path):
    """Keep uploaded videos and GPU results inside one developer namespace."""
    app, gateway = make_test_app(tmp_path, candidates=False, key_prefix="dev/alice/")
    client = TestClient(app)
    submit_video_job(client)
    assert app.state.get_modal_worker().tick()
    assert gateway.assignment["input_object"]["key"].startswith("dev/alice/videos/")
    assert gateway.assignment["output_prefix"].startswith("dev/alice/jobs/")
    assert app.state.get_modal_worker().tick()
