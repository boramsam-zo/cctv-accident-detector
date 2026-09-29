"""Runpod GPU Pod coordination through the backend's internal API."""

import hashlib
import json
import math
from datetime import timedelta

from sqlalchemy import select

from .models import Asset, Event, Job, PodWorker, Run, Video, now


def initial_result(video: Video) -> dict:
    """새 분석 실행에 사용할 영상 정보와 초기 단계 상태를 만든다."""
    return {
        "video": {"duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                  "recorded_at": video.recorded_at.isoformat() if video.recorded_at else None,
                  "original_asset_id": f"source-{video.id}"},
        "coverage": {"requested_start_seconds": 0.0, "requested_end_seconds": video.duration_seconds,
                     "scheduled_windows": 0, "predicted_windows": 0,
                     "unclassified_windows": 0, "pending_windows": 0, "unknown_ranges": []},
        "models": None,
        "stages": {name: {"status": "pending", "reason_code": None}
                   for name in ("objects", "accident", "evidence", "vlm", "rag", "report")},
        "candidates": [], "errors": [],
    }


class PodCoordinator:
    def __init__(self, sessions, storage, settings):
        """작업 상태 저장소, S3 접근 객체, worker 설정을 보관한다."""
        self.sessions, self.storage, self.settings = sessions, storage, settings

    def register(self, payload: dict) -> dict:
        """Runpod worker를 등록하고 동일 ID의 등록 정보 충돌을 확인한다."""
        with self.sessions.begin() as db:
            worker = db.get(PodWorker, payload["worker_instance_id"])
            if worker:
                if worker.pod_id != payload["pod_id"] or worker.models != payload["models"]:
                    raise ValueError("worker_registration_conflict")
            else:
                db.add(PodWorker(id=payload["worker_instance_id"], pod_id=payload["pod_id"],
                                 status="starting", models=payload["models"],
                                 started_at=payload["started_at"]))
        return {"worker_instance_id": payload["worker_instance_id"], "status": "registered"}

    def heartbeat(self, worker_id: str, payload: dict) -> dict:
        """worker 상태와 처리 진행 시각을 갱신하고 실행 임대를 연장한다."""
        with self.sessions.begin() as db:
            worker = db.get(PodWorker, worker_id)
            if worker is None:
                raise ValueError("worker_not_registered")
            active = payload.get("active_run_id")
            if worker.active_run_id and active != worker.active_run_id:
                raise ValueError("active_run_cannot_be_cleared")
            if active:
                run = db.get(Run, active)
                if run is None or run.worker_instance_id != worker_id or run.status != "running":
                    raise ValueError("run_not_owned_by_worker")
                pts = payload.get("processed_pts")
                if pts is not None:
                    if run.processed_pts is not None and pts < run.processed_pts:
                        raise ValueError("processed_pts_regressed")
                    run.processed_pts = pts
                run.lease_until = now() + timedelta(seconds=self.settings.worker_lease_seconds)
            if payload["status"] not in {"starting", "ready", "degraded", "unhealthy", "stopping"}:
                raise ValueError("invalid_worker_status")
            worker.status = payload["status"]
            worker.last_heartbeat_at = now()
            worker.gpu_memory_used_bytes = payload.get("gpu_memory_used_bytes")
            worker.active_run_id = active
            worker.processed_pts = payload.get("processed_pts")
        return {"worker_instance_id": worker_id, "received_at": now().isoformat()}

    def claim(self, worker_id: str) -> dict | None:
        """준비된 worker에 가장 오래 대기한 실행을 할당한다."""
        with self.sessions.begin() as db:
            worker = db.get(PodWorker, worker_id)
            if worker is None or worker.status != "ready":
                raise ValueError("worker_not_ready")
            if worker.active_run_id:
                raise ValueError("worker_already_busy")
            run = db.scalars(select(Run).where(Run.status == "queued")
                             .order_by(Run.created_at).with_for_update(skip_locked=True)).first()
            if run is None:
                return None
            job = db.get(Job, run.job_id)
            video = db.get(Video, job.video_id)
            run.status, run.worker_instance_id, run.pod_id = "running", worker_id, worker.pod_id
            run.attempt += 1
            run.lease_until = now() + timedelta(seconds=self.settings.worker_lease_seconds)
            worker.active_run_id = run.id
            result = dict(run.result or initial_result(video))
            stages = dict(result["stages"])
            stages["accident"] = {"status": "running", "reason_code": None}
            result["stages"] = stages
            run.result = result
            return {"schema_version": "service-draft-v0.2", "job_id": job.id, "run_id": run.id,
                    "source_video_id": video.id,
                    "input_object": {"bucket": self.storage.bucket, "key": video.s3_key,
                                     "sha256": video.sha256},
                    "output_prefix": f"jobs/{job.id}/runs/{run.id}/attempt-{run.attempt}/",
                    "analysis_profile": {"id": run.profile_id, "analysis_mode": "file_realtime_1x"},
                    "attempt": run.attempt, "lease_seconds": self.settings.worker_lease_seconds}

    def _manifest(self, ref: str, digest: str, prefix: str) -> dict:
        """허용된 S3 경로의 JSON manifest를 읽고 SHA256을 확인한다."""
        key = self.storage.key_from_ref(ref)
        if not key.startswith(prefix) or not key.endswith(".json"):
            raise ValueError("invalid_manifest_key")
        raw = self.storage.get_bytes(key, 2_000_000)
        if len(digest) != 64 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("manifest_sha256_mismatch")
        return json.loads(raw)

    def _asset(self, db, run: Run, event_id: str, index: int, kind: str,
               item: dict, prefix: str) -> str:
        """근거 파일의 경로·형식·해시를 확인해 asset 행을 추가한다."""
        key = self.storage.key_from_ref(item.get("key") or item.get("s3_uri", ""))
        mime = item.get("mime_type")
        digest = item.get("sha256", "")
        if not key.startswith(prefix) or not self.storage.exists(key):
            raise ValueError("invalid_asset_key")
        if mime not in ({"video/mp4"} if kind == "clip" else {"image/jpeg", "image/png"}):
            raise ValueError("invalid_asset_mime")
        limit = self.settings.max_gemini_clip_bytes if kind == "clip" else 5_000_000
        if len(digest) != 64 or hashlib.sha256(self.storage.get_bytes(key, limit)).hexdigest() != digest:
            raise ValueError("asset_sha256_mismatch")
        asset_id = f"{event_id}-{kind}-{index}"
        db.add(Asset(id=asset_id, run_id=run.id, s3_key=key, kind=kind,
                     sha256=digest, mime_type=mime))
        return asset_id

    def event(self, run_id: str, payload: dict) -> dict:
        """사고 후보 manifest와 근거를 검증해 실행 결과에 이벤트를 등록한다."""
        with self.sessions.begin() as db:
            run = db.get(Run, run_id)
            if run is None or run.status != "running" or run.worker_instance_id != payload["worker_instance_id"]:
                raise ValueError("run_not_owned_by_worker")
            previous = db.get(Event, payload["event_id"])
            if previous:
                if (previous.run_id != run_id or previous.sequence_number != payload["sequence_number"]
                        or previous.manifest_sha256 != payload["manifest_sha256"]):
                    raise ValueError("event_conflict")
                return {"event_id": previous.id, "status": "registered"}
            if db.scalars(select(Event).where(Event.run_id == run_id,
                                              Event.sequence_number == payload["sequence_number"])).first():
                raise ValueError("sequence_conflict")
            job = db.get(Job, run.job_id)
            video = db.get(Video, job.video_id)
            prefix = f"jobs/{job.id}/runs/{run.id}/attempt-{run.attempt}/"
            manifest = self._manifest(payload["manifest_key"], payload["manifest_sha256"], prefix)
            if (manifest.get("schema_version") != "service-draft-v0.2" or manifest.get("is_demo")
                    or manifest.get("run_id") != run_id or manifest.get("event_id") != payload["event_id"]
                    or manifest.get("sequence_number") != payload["sequence_number"]):
                raise ValueError("event_manifest_identity_mismatch")
            start, end = manifest.get("start_seconds"), manifest.get("end_seconds")
            if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                    or not 0 <= start < end <= video.duration_seconds
                    or start != payload["start_seconds"] or end != payload["end_seconds"]):
                raise ValueError("invalid_event_time")
            candidate_time = manifest.get("candidate_time_s")
            if (not isinstance(candidate_time, (int, float)) or isinstance(candidate_time, bool)
                    or not math.isfinite(candidate_time) or not start <= candidate_time <= end
                    or candidate_time != payload["candidate_time_s"]):
                raise ValueError("invalid_candidate_time")
            evidence = manifest.get("evidence") or {}
            clip, frames = evidence.get("clip"), evidence.get("frames") or []
            if not clip and not frames:
                raise ValueError("candidate_has_no_evidence")
            clip_id = self._asset(db, run, payload["event_id"], 0, "clip", clip, prefix) if clip else None
            frame_data = []
            for index, frame in enumerate(frames):
                asset_id = self._asset(db, run, payload["event_id"], index, "frame", frame, prefix)
                frame_data.append({"asset_id": asset_id,
                                   "source_time_seconds": frame.get("source_time_seconds")})
            event_data = {key: value for key, value in manifest.items() if key != "evidence"}
            event_data.update({"label": "suspected_accident", "evidence": {
                "clip_asset_id": clip_id, "clip_start_seconds": evidence.get("clip_start_seconds"),
                "clip_end_seconds": evidence.get("clip_end_seconds"), "frames": frame_data},
                "human_review": {"status": "unreviewed", "review_id": None,
                                 "review_revision": 0, "report_revision": None, "note": None}})
            db.add(Event(id=payload["event_id"], run_id=run_id,
                         sequence_number=payload["sequence_number"],
                         manifest_key=self.storage.key_from_ref(payload["manifest_key"]),
                         manifest_sha256=payload["manifest_sha256"], data=event_data))
            result = dict(run.result or initial_result(video))
            result["candidates"] = [*result["candidates"], event_data]
            stages = dict(result["stages"])
            stages["evidence"] = {"status": "completed", "reason_code": None}
            result["stages"] = stages
            run.result, run.outcome = result, "candidates_found"
            return {"event_id": payload["event_id"], "status": "registered"}

    def complete(self, run_id: str, payload: dict) -> dict:
        """최종 manifest의 처리 범위를 확인하고 실행 결과를 확정한다."""
        with self.sessions.begin() as db:
            run = db.get(Run, run_id)
            if run is None or run.worker_instance_id != payload["worker_instance_id"]:
                raise ValueError("run_not_owned_by_worker")
            manifest_key = self.storage.key_from_ref(payload["manifest_key"])
            if run.manifest_key:
                if run.manifest_key != manifest_key:
                    raise ValueError("final_manifest_conflict")
                return {"run_id": run_id, "status": run.status}
            if run.status != "running":
                raise ValueError("run_not_running")
            job = db.get(Job, run.job_id)
            video = db.get(Video, job.video_id)
            prefix = f"jobs/{job.id}/runs/{run.id}/attempt-{run.attempt}/"
            manifest = self._manifest(manifest_key, payload["manifest_sha256"], prefix)
            if manifest.get("schema_version") != "service-draft-v0.2" or manifest.get("run_id") != run_id:
                raise ValueError("final_manifest_identity_mismatch")
            coverage = manifest.get("coverage") or {}
            counts = [coverage.get(name) for name in ("scheduled_windows", "predicted_windows",
                                                         "unclassified_windows", "pending_windows")]
            if (not all(isinstance(value, int) and value >= 0 for value in counts)
                    or counts[0] == 0 or counts[0] != sum(counts[1:])):
                raise ValueError("coverage_count_mismatch")
            result = dict(run.result or initial_result(video))
            result["coverage"], result["models"] = coverage, manifest.get("models")
            result["errors"] = manifest.get("errors", [])
            stages = dict(result["stages"])
            for name in ("accident", "objects", "evidence"):
                status = "completed" if result["candidates"] or name == "accident" else "skipped"
                stages[name] = {"status": status,
                                "reason_code": None if status == "completed" else "no_candidates"}
            if not result["candidates"]:
                reason = "no_candidates" if counts[2] == counts[3] == 0 else "no_usable_candidate"
                for name in ("vlm", "rag", "report"):
                    stages[name] = {"status": "skipped", "reason_code": reason}
            result["stages"] = stages
            run.result, run.manifest_key = result, manifest_key
            if result["candidates"]:
                run.outcome = "candidates_found"
                pending = any("vlm" not in event for event in result["candidates"])
                failed = any(event.get("vlm", {}).get("status") == "failed"
                             for event in result["candidates"])
                run.status = "enriching" if pending else "partial" if failed or counts[2] or counts[3] else "completed"
            else:
                run.outcome = "unknown" if counts[2] or counts[3] else "no_candidates"
                run.status = "partial" if run.outcome == "unknown" else "completed"
            run.lease_until = None
            db.get(PodWorker, run.worker_instance_id).active_run_id = None
            return {"run_id": run_id, "status": run.status,
                    "detection_outcome": run.outcome}
