"""Runpod 조정 서비스의 작업 소유권과 manifest 검증을 확인한다."""

import hashlib
import json
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from services.backend.db import make_session_factory
from services.backend.models import Job, PodWorker, Run, Video
from services.backend.pod import PodCoordinator, initial_result
from services.backend.settings import Settings
from services.backend.storage import S3Storage


@pytest.fixture
def pod_context(tmp_path, monkeypatch):
    """Pod 조정 테스트용 SQLite 작업과 Moto S3 버킷을 준비한다."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="backend-pod-test")
        storage = S3Storage("backend-pod-test", client=client)
        sessions = make_session_factory(f"sqlite:///{tmp_path / 'pod.db'}")
        settings = Settings(
            database_url="", s3_bucket=storage.bucket, s3_endpoint_url=None,
            aws_region="us-east-1", pod_worker_token="test", gemini_api_key="test",
            gemini_model="test", app_api_key="test", analysis_profile_id="profile-1",
            max_upload_bytes=1_000, max_gemini_clip_bytes=1_000, worker_lease_seconds=60,
        )
        with sessions.begin() as db:
            video = Video(id="video-1", filename="sample.mp4", s3_key="videos/video-1/original.mp4",
                          sha256="a" * 64, size_bytes=100, content_type="video/mp4", duration_seconds=10.0)
            db.add(video)
            db.add(Job(id="job-1", video_id=video.id, active_run_id="run-1"))
            db.add(Run(id="run-1", job_id="job-1", profile_id="profile-1", result=initial_result(video)))
        yield PodCoordinator(sessions, storage, settings), sessions, storage


def ready_worker(coordinator):
    """작업을 받을 수 있는 Runpod worker를 등록하고 준비 상태로 만든다."""
    coordinator.register({"pod_id": "pod-1", "worker_instance_id": "worker-1",
                          "started_at": datetime.now(timezone.utc), "models": {}})
    coordinator.heartbeat("worker-1", {"status": "ready", "active_run_id": None})


def test_claim_assigns_one_run_and_rejects_busy_worker(pod_context):
    """대기 작업 할당 후 같은 worker의 중복 할당을 막는지 확인한다."""
    coordinator, sessions, _ = pod_context
    ready_worker(coordinator)

    assignment = coordinator.claim("worker-1")

    assert assignment["run_id"] == "run-1"
    assert assignment["input_object"]["key"] == "videos/video-1/original.mp4"
    assert assignment["attempt"] == 1
    with sessions() as db:
        assert db.get(Run, "run-1").status == "running"
        assert db.get(PodWorker, "worker-1").active_run_id == "run-1"
    with pytest.raises(ValueError, match="worker_already_busy"):
        coordinator.claim("worker-1")


def test_heartbeat_rejects_progress_regression(pod_context):
    """heartbeat의 처리 시각이 이전 값보다 작으면 거부하는지 확인한다."""
    coordinator, sessions, _ = pod_context
    ready_worker(coordinator)
    coordinator.claim("worker-1")
    coordinator.heartbeat("worker-1", {"status": "ready", "active_run_id": "run-1", "processed_pts": 4.0})

    with pytest.raises(ValueError, match="processed_pts_regressed"):
        coordinator.heartbeat("worker-1", {"status": "ready", "active_run_id": "run-1", "processed_pts": 3.0})

    with sessions() as db:
        assert db.get(Run, "run-1").processed_pts == 4.0


def test_final_manifest_rejects_inconsistent_coverage(pod_context):
    """최종 처리 창 수가 맞지 않으면 실행을 완료하지 않는지 확인한다."""
    coordinator, sessions, storage = pod_context
    ready_worker(coordinator)
    assignment = coordinator.claim("worker-1")
    key = assignment["output_prefix"] + "final.json"
    raw = json.dumps({"schema_version": "service-draft-v0.2", "run_id": "run-1",
                      "coverage": {"scheduled_windows": 2, "predicted_windows": 1,
                                   "unclassified_windows": 0, "pending_windows": 0}}).encode()
    storage.client.put_object(Bucket=storage.bucket, Key=key, Body=raw)

    with pytest.raises(ValueError, match="coverage_count_mismatch"):
        coordinator.complete("run-1", {"worker_instance_id": "worker-1", "manifest_key": key,
                                       "manifest_sha256": hashlib.sha256(raw).hexdigest()})

    with sessions() as db:
        assert db.get(Run, "run-1").status == "running"
        assert db.get(Run, "run-1").manifest_key is None


def test_manifest_rejects_wrong_hash_before_parsing(pod_context):
    """manifest의 SHA256과 허용 경로를 읽기 전에 검증하는지 확인한다."""
    coordinator, _, storage = pod_context
    storage.client.put_object(Bucket=storage.bucket, Key="allowed/event.json", Body=b"{}")
    with pytest.raises(ValueError, match="manifest_sha256_mismatch"):
        coordinator._manifest("allowed/event.json", "0" * 64, "allowed/")
    with pytest.raises(ValueError, match="invalid_manifest_key"):
        coordinator._manifest("other/event.json", "0" * 64, "allowed/")
