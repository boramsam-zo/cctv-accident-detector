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

    def put_model_weight(self, key, stream, max_bytes):
        data = stream.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("empty_or_oversized_model_weight")
        self.objects[key] = data
        return StoredObject(key, hashlib.sha256(data).hexdigest(), len(data))

    def delete(self, key):
        self.objects.pop(key, None)

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
            annotated_clip_key = prefix + "events/annotated.mp4"
            frame_key = prefix + "events/frame.jpg"
            self.storage.objects[clip_key] = b"clip"
            self.storage.objects[annotated_clip_key] = b"annotated"
            self.storage.objects[frame_key] = b"frame"
            manifest = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                        "event_id": event_id, "sequence_number": 1,
                        "start_seconds": 2.0, "end_seconds": 4.0, "candidate_time_s": 3.0,
                        "object_observations": [], "evidence": {
                            "clip_start_seconds": 1.0, "clip_end_seconds": 5.0,
                            "clip": {"key": clip_key, "sha256": hashlib.sha256(b"clip").hexdigest(),
                                     "mime_type": "video/mp4"},
                            "annotated_clip": {
                                "key": annotated_clip_key,
                                "sha256": hashlib.sha256(b"annotated").hexdigest(),
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
    def analyze(self, event, media, *, model=None, prompt_override="", prompt_mode="prepend"):
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


class FlakyGemini(FakeGemini):
    def __init__(self):
        self.calls = 0

    def analyze(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary Gemini outage")
        return super().analyze(*args, **kwargs)


def make_test_app(tmp_path, candidates=True, corrupt=False, key_prefix="", gemini=None):
    """Create an API with isolated DB, S3, Modal, and Gemini dependencies."""
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'modal.db'}",
                        s3_bucket="test-bucket", s3_endpoint_url=None,
                        aws_region="ap-northeast-2",
                        gemini_api_key="test", gemini_model="fake", app_api_key="test",
                        analysis_profile_id="profile-1", max_upload_bytes=1000,
                        max_gemini_clip_bytes=1000,
                        s3_key_prefix=key_prefix)
    storage = MemoryStorage()
    gateway = FakeGateway(storage, candidates=candidates, corrupt=corrupt)
    app = create_app(settings, storage=storage, gemini=gemini or FakeGemini(),
                     video_probe=lambda _: 10.0, modal_gateway=gateway)
    return app, gateway


def submit_video_job(client, profile_id="profile-1", defer_vlm=False):
    """Upload one MP4 and request asynchronous analysis through public APIs."""
    headers = {"Authorization": "Bearer test", "Idempotency-Key": "upload-1"}
    video = b"\x00\x00\x00\x18ftypmp42" + b"x" * 20
    uploaded = client.post("/api/v1/videos", files={"file": ("sample.mp4", video, "video/mp4")},
                           headers=headers)
    assert uploaded.status_code == 201
    headers["Idempotency-Key"] = "job-1"
    response = client.post("/api/v1/jobs", json={"source_video_id": uploaded.json()["source_video_id"],
                                                  "analysis_profile_id": profile_id,
                                                  "defer_vlm": defer_vlm}, headers=headers)
    assert response.status_code == 202
    return response.json()["job_id"], headers


def test_modal_candidate_flow_reaches_gemini_and_public_asset_api(tmp_path):
    """Check uploaded video through Modal evidence, Gemini, and UI-facing APIs."""
    app, gateway = make_test_app(tmp_path)
    client = TestClient(app)
    options = client.get("/api/v1/vlm-options", headers={"Authorization": "Bearer test"}).json()
    assert [preset["id"] for preset in options["prompt_presets"]] == ["scene-facts-v2", "version1", "prompt2"]
    assert options["default_prompt_preset"] == "scene-facts-v2"
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
    annotated_clip_id = result["candidates"][0]["evidence"]["annotated_clip_asset_id"]
    assert client.get(f"/api/v1/assets/{clip_id}/url", headers=headers).status_code == 200
    assert client.get(f"/api/v1/assets/{annotated_clip_id}/url", headers=headers).status_code == 200


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


def test_rag_readiness_is_authenticated_and_has_no_paid_calls(tmp_path):
    app, _ = make_test_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/v1/rag/status").status_code == 401
    response = client.get("/api/v1/rag/status", headers={"Authorization": "Bearer test"})
    assert response.json() == {"status": "disabled", "store": "file"}


def test_upload_to_grounded_report_with_three_gemini_requests(tmp_path, scene_payload):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import Mock
    from services.backend.gemini_vlm import GeminiVLM, GeminiResult
    from services.backend.rag import GeminiRag, REPORT_PROMPT, ROOT, load_corpus

    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1, 0])])
    rows, digest = load_corpus(ROOT / "data/rag/chunks.jsonl")
    index = tmp_path / "vectors.json"
    index.write_text(json.dumps({"corpus_sha256": digest, "model": "gemini-embedding-001",
        "dimensions": 2, "input_version": "embedding-input-v1",
        "vectors": {r["chunk_id"]: [1, 0] for r in rows}}))

    def generate(**kwargs):
        if kwargs["config"].get("response_json_schema", {}).get("title") == GeminiResult.__name__:
            input_context = json.loads(kwargs["contents"][0].split("input JSON:\n")[-1])
            payload = scene_payload(input_context["media"][0]["asset_id"], accident="present", lane="present")
        else:
            context = json.loads(kwargs["contents"][len(REPORT_PROMPT) + 1:])
            citation = next(c for c in context["retrieval"]["citations"] if "경찰" in c["agencies"])
            payload = {"summary": "교통 위험 확인 필요", "limitations": ["부상 미확인"], "agencies": [
                {"agency": "경찰", "role": "교통 안전", "reason": "차로 점유",
                 "selection_status": "conditional", "conditions_to_confirm": ["현장 위험 확인"],
                 "citation_chunk_ids": [citation["chunk_id"]]}]}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    client.models.generate_content.side_effect = generate
    app, _ = make_test_app(tmp_path, gemini=GeminiVLM("test", "fake", client=client))
    api = TestClient(app)
    job_id, headers = submit_video_job(api)
    assert app.state.get_modal_worker().tick()
    assert app.state.get_modal_worker().tick()
    worker = app.state.get_enrichment_worker()
    worker.rag = GeminiRag(client, replace(worker.settings, rag_index_path=str(index), rag_embedding_dimensions=2))
    assert worker.tick()
    result = api.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "completed"
    candidate = result["candidates"][0]
    assert candidate["report"]["generation_status"] == "completed"
    assert candidate["report"]["structured"]["agencies"][0]["agency"] == "경찰"
    assert candidate["vlm"]["raw_output"]["schema_version"] == "scene-facts-v2"
    assert candidate["vlm"]["validation"]["provenance"] == "passed"
    assert candidate["rag_input"]["features"]["lane_blockage"]["state"] == "present"
    assert "차로 점유" in candidate["retrieval"]["query"]
    assert "산림 연소" not in candidate["retrieval"]["query"]
    citation_ids = {c["chunk_id"] for c in candidate["retrieval"]["citations"]}
    assert set(candidate["report"]["agencies"][0]["citation_chunk_ids"]) <= citation_ids
    assert client.models.generate_content.call_count == 2
    client.models.embed_content.assert_called_once()
    assert not worker.tick()


def test_modal_candidate_waits_for_manual_vlm_request(tmp_path):
    app, _ = make_test_app(tmp_path)
    client = TestClient(app)
    job_id, headers = submit_video_job(client, defer_vlm=True)

    assert app.state.get_modal_worker().tick()
    assert app.state.get_modal_worker().tick()
    waiting = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert waiting["status"] == "awaiting_vlm"
    assert waiting["stages"]["vlm"] == {
        "status": "pending", "reason_code": "manual_start_required"}
    assert not app.state.get_enrichment_worker().tick()

    trigger_headers = {**headers, "Idempotency-Key": "vlm-start-1"}
    triggered = client.post(f"/api/v1/jobs/{job_id}/vlm", headers=trigger_headers)
    assert triggered.status_code == 202, triggered.text
    assert triggered.json()["status"] == "enriching"
    assert app.state.get_enrichment_worker().tick()
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"] == "completed"


def test_failed_vlm_exposes_reason_and_can_retry_without_modal(tmp_path):
    gemini = FlakyGemini()
    app, gateway = make_test_app(tmp_path, gemini=gemini)
    client = TestClient(app)
    job_id, headers = submit_video_job(client)

    assert app.state.get_modal_worker().tick()
    assert app.state.get_modal_worker().tick()
    assert app.state.get_enrichment_worker().tick()
    failed = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert failed["status"] == "partial"
    assert failed["candidates"][0]["vlm"]["reason_code"] == "RuntimeError"
    assert failed["candidates"][0]["vlm"]["error_message"] == "temporary Gemini outage"

    trigger_headers = {**headers, "Idempotency-Key": "vlm-retry-1"}
    retried = client.post(f"/api/v1/jobs/{job_id}/vlm", headers=trigger_headers)
    assert retried.status_code == 202, retried.text
    assert retried.json()["candidate_count"] == 1
    assert app.state.get_enrichment_worker().tick()

    completed = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert completed["status"] == "completed"
    assert completed["candidates"][0]["vlm"]["status"] == "completed"
    assert completed["candidates"][0]["rag_input"]["event_id"].endswith("-001")
    assert gateway.assignment is not None


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


def test_registered_profile_uploads_weights_and_reaches_modal_assignment(tmp_path):
    app, gateway = make_test_app(tmp_path, candidates=False, key_prefix="dev/alice/")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test"}

    created = client.post(
        "/api/v1/analysis-profiles",
        data={"display_name": "custom profile", "description": "test weights",
              "accident_family": "X3D-S", "object_family": "YOLO11"},
        files={"accident_weights": ("x3d.pt", b"x3d-weights", "application/octet-stream"),
               "object_weights": ("yolo.pt", b"yolo-weights", "application/octet-stream")},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    profile_id = profile["analysis_profile_id"]
    assert profile["models"]["accident"]["weights"]["sha256"] == hashlib.sha256(b"x3d-weights").hexdigest()
    assert len(client.get("/api/v1/analysis-profiles", headers=headers).json()["items"]) == 2

    submit_video_job(client, profile_id)
    assert app.state.get_modal_worker().tick()

    assert gateway.assignment["analysis_profile"]["id"] == profile_id
    assert gateway.assignment["model_weights"]["x3d"]["key"].startswith(
        f"dev/alice/model-profiles/{profile_id}/")
    assert gateway.assignment["model_weights"]["yolo"]["sha256"] == hashlib.sha256(b"yolo-weights").hexdigest()
    assert gateway.assignment["model_families"] == {
        "x3d": "X3D-S", "yolo": "YOLO11"}
