"""Submit Modal GPU inference and ingest its verified S3 result."""

import hashlib
import json
import logging
import math

from sqlalchemy import select

from .models import Asset, Event, Job, Run, Video

log = logging.getLogger(__name__)


class ModalGateway:
    def __init__(self, settings):
        """Keep the deployed Modal Function location without opening a connection."""
        self.settings = settings

    def spawn(self, assignment: dict) -> str:
        """Submit one GPU analysis and return its durable function call ID."""
        import modal

        function = modal.Function.from_name(
            self.settings.modal_app_name, self.settings.modal_function_name,
            environment_name=self.settings.modal_environment,
        )
        return function.spawn(assignment).object_id

    def poll(self, call_id: str) -> dict | None:
        """Return a completed GPU result without blocking, or None while it runs."""
        import modal

        try:
            return modal.FunctionCall.from_id(call_id).get(timeout=0)
        except TimeoutError:
            return None


class ModalWorker:
    def __init__(self, sessions, storage, gateway, key_prefix: str = ""):
        """Bind queued runs, Modal calls, and the shared S3 evidence store."""
        self.sessions, self.storage, self.gateway = sessions, storage, gateway
        self.key_prefix = key_prefix

    def _verified_json(self, key: str, digest: str, prefix: str) -> dict:
        """Read a JSON object only from this run's output prefix and check its digest."""
        key = self.storage.key_from_ref(key)
        if not key.startswith(prefix) or not key.endswith(".json") or len(digest) != 64:
            raise ValueError("invalid_manifest_reference")
        raw = self.storage.get_bytes(key, 2_000_000)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("manifest_sha256_mismatch")
        return json.loads(raw)

    def _asset(self, db, run: Run, event_id: str, kind: str, index: int,
               item: dict, prefix: str) -> str:
        """Verify the S3 evidence bytes before registering a public asset."""
        key = self.storage.key_from_ref(item.get("key", ""))
        mime = item.get("mime_type")
        digest = item.get("sha256", "")
        if not key.startswith(prefix) or not self.storage.exists(key):
            raise ValueError("invalid_asset_key")
        if mime not in ({"video/mp4"} if kind == "clip" else {"image/jpeg", "image/png"}):
            raise ValueError("invalid_asset_mime")
        if len(digest) != 64 or hashlib.sha256(self.storage.get_bytes(key, 20_000_000)).hexdigest() != digest:
            raise ValueError("asset_sha256_mismatch")
        asset_id = f"{event_id}-{kind}-{index}"
        db.add(Asset(id=asset_id, run_id=run.id, s3_key=key, kind=kind,
                     sha256=digest, mime_type=mime))
        return asset_id

    def _ingest(self, run_id: str, result_ref: dict) -> None:
        """Validate Modal manifests and commit the final run and candidate state."""
        if result_ref.get("schema_version") != "modal-inference-v1" or result_ref.get("run_id") != run_id:
            raise ValueError("modal_result_identity_mismatch")
        with self.sessions.begin() as db:
            run = db.get(Run, run_id)
            if run is None or run.status != "running":
                raise ValueError("run_not_running")
            job = db.get(Job, run.job_id)
            video = db.get(Video, job.video_id)
            prefix = f"{self.key_prefix}jobs/{job.id}/runs/{run.id}/attempt-{run.attempt}/"
            final_key = self.storage.key_from_ref(result_ref["final_manifest_key"])
            final = self._verified_json(final_key, result_ref["final_manifest_sha256"], prefix)
            if final.get("schema_version") != "service-draft-v0.2" or final.get("run_id") != run_id:
                raise ValueError("final_manifest_identity_mismatch")
            coverage = final.get("coverage") or {}
            counts = [coverage.get(name) for name in ("scheduled_windows", "predicted_windows",
                                                     "unclassified_windows", "pending_windows")]
            if (not all(type(value) is int and value >= 0 for value in counts)
                    or counts[0] == 0 or counts[0] != sum(counts[1:])):
                raise ValueError("coverage_count_mismatch")
            candidates = []
            for index, ref in enumerate(result_ref.get("events", []), start=1):
                manifest = self._verified_json(ref["manifest_key"], ref["manifest_sha256"], prefix)
                event_id = manifest.get("event_id")
                start, end, candidate = (manifest.get(name) for name in
                                         ("start_seconds", "end_seconds", "candidate_time_s"))
                if (manifest.get("schema_version") != "service-draft-v0.2"
                        or manifest.get("run_id") != run_id or manifest.get("sequence_number") != index
                        or not isinstance(event_id, str) or not event_id.startswith(f"{run_id}-")
                        or not all(type(value) in (int, float) and math.isfinite(value)
                                   for value in (start, end, candidate))
                        or not 0 <= start <= candidate <= end <= video.duration_seconds or start == end
                        or db.get(Event, event_id) is not None):
                    raise ValueError("event_manifest_invalid")
                evidence = manifest.get("evidence") or {}
                clip = evidence.get("clip")
                frames = evidence.get("frames") or []
                if not clip and not frames:
                    raise ValueError("candidate_has_no_evidence")
                clip_id = self._asset(db, run, event_id, "clip", 0, clip, prefix) if clip else None
                frame_data = []
                for frame_index, frame in enumerate(frames):
                    asset_id = self._asset(db, run, event_id, "frame", frame_index, frame, prefix)
                    frame_data.append({"asset_id": asset_id,
                                       "source_time_seconds": frame.get("source_time_seconds")})
                event_data = {key: value for key, value in manifest.items() if key != "evidence"}
                event_data.update({"label": "suspected_accident", "evidence": {
                    "clip_asset_id": clip_id, "clip_start_seconds": evidence.get("clip_start_seconds"),
                    "clip_end_seconds": evidence.get("clip_end_seconds"), "frames": frame_data},
                    "human_review": {"status": "unreviewed", "review_id": None,
                                     "review_revision": 0, "report_revision": None, "note": None}})
                db.add(Event(id=event_id, run_id=run_id, sequence_number=index,
                             manifest_key=self.storage.key_from_ref(ref["manifest_key"]),
                             manifest_sha256=ref["manifest_sha256"], data=event_data))
                candidates.append(event_data)
            value = dict(run.result or {})
            value["coverage"], value["models"] = coverage, final.get("models")
            value["candidates"], value["errors"] = candidates, final.get("errors", [])
            stages = dict(value["stages"])
            for name in ("accident", "objects", "evidence"):
                status = "completed" if candidates or name == "accident" else "skipped"
                stages[name] = {"status": status,
                                "reason_code": None if status == "completed" else "no_candidates"}
            if not candidates:
                reason = "no_candidates" if counts[2] == counts[3] == 0 else "no_usable_candidate"
                for name in ("vlm", "rag", "report"):
                    stages[name] = {"status": "skipped", "reason_code": reason}
            value["stages"] = stages
            run.result, run.manifest_key = value, final_key
            run.outcome = "candidates_found" if candidates else (
                "unknown" if counts[2] or counts[3] else "no_candidates")
            run.status = "enriching" if candidates else (
                "partial" if run.outcome == "unknown" else "completed")

    def _fail(self, run_id: str, exc: Exception) -> None:
        """Persist a failed Modal submit or result so the UI does not wait forever."""
        log.error("Modal inference failed for run %s: %s", run_id, type(exc).__name__, exc_info=exc)
        with self.sessions.begin() as db:
            run = db.get(Run, run_id)
            if run and run.status in {"dispatching", "running"}:
                run.status = "failed"
                run.outcome = "unknown"
                run.error = {"stage": "accident", "code": type(exc).__name__,
                             "message": "GPU inference failed", "retryable": True}

    def tick(self) -> bool:
        """Submit one queued run or poll one in-flight Modal call."""
        with self.sessions.begin() as db:
            run = db.scalars(select(Run).where(Run.status == "queued")
                             .order_by(Run.created_at).with_for_update(skip_locked=True)).first()
            if run:
                run.status = "dispatching"
                run.attempt += 1
                job = db.get(Job, run.job_id)
                video = db.get(Video, job.video_id)
                profile = ((run.result or {}).get("execution_config") or {}).get("analysis_profile") or {
                    "id": run.profile_id, "source": "modal_secret"}
                assignment = {"schema_version": "modal-inference-v1", "job_id": job.id,
                              "run_id": run.id, "source_video_id": video.id,
                              "input_object": {"bucket": self.storage.bucket, "key": video.s3_key,
                                               "sha256": video.sha256},
                              "output_prefix": f"{self.key_prefix}jobs/{job.id}/runs/{run.id}/attempt-{run.attempt}/",
                              "attempt": run.attempt,
                              "analysis_profile": {"id": profile["id"],
                                                   "analysis_mode": "offline_video"},
                              "duration_seconds": video.duration_seconds}
                if profile.get("source") == "registered":
                    models = profile["models"]
                    assignment["model_weights"] = {
                        "x3d": models["accident"]["weights"],
                        "yolo": models["objects"]["weights"],
                    }
                    assignment["model_families"] = {
                        "x3d": models["accident"]["family"],
                        "yolo": models["objects"]["family"],
                    }
                run_id = run.id
            else:
                assignment = None
        if assignment:
            try:
                call_id = self.gateway.spawn(assignment)
                if not call_id:
                    raise ValueError("missing_modal_call_id")
                with self.sessions.begin() as db:
                    run = db.get(Run, run_id)
                    run.modal_call_id = call_id
                    run.status = "running"
            except Exception as exc:
                self._fail(run_id, exc)
            return True
        with self.sessions() as db:
            calls = [(run.id, run.modal_call_id) for run in db.scalars(
                select(Run).where(Run.status == "running", Run.modal_call_id.is_not(None))
                .order_by(Run.created_at)).all()]
        for run_id, call_id in calls:
            try:
                result = self.gateway.poll(call_id)
                if result is None:
                    continue
                self._ingest(run_id, result)
            except Exception as exc:
                self._fail(run_id, exc)
            return True
        return False
