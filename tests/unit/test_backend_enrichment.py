"""사고 후보 후처리에서 근거 무결성과 DB 반영을 확인한다."""

import hashlib
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from services.backend.db import make_session_factory
from services.backend.models import Asset, Event, Job, Report, Run, Video
from services.backend.result_state import initial_result
from services.backend.settings import Settings
from services.backend.storage import S3Storage
from services.backend.worker import EnrichmentWorker


@pytest.fixture
def enrichment_context(tmp_path, monkeypatch):
    """Moto S3와 SQLite에 사고 후보·근거를 준비한다."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="backend-enrichment-test")
        storage = S3Storage("backend-enrichment-test", client=client)
        sessions = make_session_factory(f"sqlite:///{tmp_path / 'enrichment.db'}")
        settings = Settings(
            database_url="", s3_bucket=storage.bucket, s3_endpoint_url=None,
            aws_region="us-east-1", gemini_api_key="test",
            gemini_model="test", app_api_key="test", analysis_profile_id="profile-1",
            max_upload_bytes=1_000, max_gemini_clip_bytes=1_000,
        )
        event_data = {"event_id": "event-1", "start_seconds": 2.0, "end_seconds": 4.0,
                      "candidate_time_s": 3.0, "evidence": {
                          "clip_asset_id": "clip-1", "frames": [{"asset_id": "frame-1"}]}}
        with sessions.begin() as db:
            video = Video(id="video-1", filename="sample.mp4", s3_key="videos/video-1/original.mp4",
                          sha256="a" * 64, size_bytes=100, content_type="video/mp4", duration_seconds=10.0)
            result = initial_result(video)
            result["candidates"] = [event_data]
            db.add(video)
            db.add(Job(id="job-1", video_id=video.id, active_run_id="run-1"))
            db.add(Run(id="run-1", job_id="job-1", profile_id="profile-1", status="enriching",
                       outcome="candidates_found", result=result))
            db.add(Event(id="event-1", run_id="run-1", sequence_number=1,
                         manifest_key="manifest.json", manifest_sha256="a" * 64, data=event_data))
            for asset_id, kind, blob, mime in [
                ("clip-1", "clip", b"clip-bytes", "video/mp4"),
                ("frame-1", "frame", b"frame-bytes", "image/png"),
            ]:
                key = f"evidence/{asset_id}"
                storage.client.put_object(Bucket=storage.bucket, Key=key, Body=blob)
                db.add(Asset(id=asset_id, run_id="run-1", s3_key=key, kind=kind,
                             sha256=hashlib.sha256(blob).hexdigest(), mime_type=mime))
        gemini = Mock()
        worker = EnrichmentWorker(sessions, storage, gemini, settings)
        yield worker, sessions, storage, gemini


def test_worker_persists_verified_media_result_and_report(enrichment_context):
    """검증한 clip·frame의 Gemini 결과와 리포트가 DB에 저장되는지 확인한다."""
    worker, sessions, _, gemini = enrichment_context
    gemini.analyze.return_value = {
        "status": "completed", "summary": "차량 두 대가 보입니다.",
        "observations": [], "uncertainties": [], "provider_model": "test-model",
        "rag_input": {"event_id": "event-1", "candidate_time_s": 3.0,
                      "description": "차량 두 대가 보입니다.", "operator_confirmed": None},
    }

    assert worker.tick() is True

    media = gemini.analyze.call_args.args[1]
    assert media == [("clip-1", "video/mp4", b"clip-bytes"),
                     ("frame-1", "image/png", b"frame-bytes")]
    with sessions() as db:
        event = db.get(Event, "event-1")
        run = db.get(Run, "run-1")
        assert event.data["rag_input"]["candidate_time_s"] == 3.0
        assert event.data["report"]["status"] == "completed"
        assert run.status == "completed"
        assert run.result["candidates"][0]["vlm"]["status"] == "completed"
        assert db.query(Report).count() == 1
    assert worker.tick() is False
    gemini.analyze.assert_called_once()


def test_worker_rejects_modified_evidence_before_gemini(enrichment_context):
    """근거 파일 해시가 바뀌면 Gemini 호출 없이 부분 실패로 기록하는지 확인한다."""
    worker, sessions, storage, gemini = enrichment_context
    storage.client.put_object(Bucket=storage.bucket, Key="evidence/frame-1", Body=b"modified")

    assert worker.tick() is True

    gemini.analyze.assert_not_called()
    with sessions() as db:
        event = db.get(Event, "event-1")
        run = db.get(Run, "run-1")
        assert event.data["vlm"]["status"] == "failed"
        assert event.data["vlm"]["reason_code"] == "ValueError"
        assert event.data["vlm"]["error_message"] == "evidence_sha256_mismatch"
        assert "rag_input" not in event.data
        assert event.data["retrieval"]["status"] == "insufficient_evidence"
        assert run.status == "partial"
