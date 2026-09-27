import hashlib
import hmac
import json
import base64
from io import BytesIO
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from . import models  # Register tables before create_all.
from .db import make_session_factory
from .gemini_vlm import GeminiVLM
from .models import Asset, Event, Idempotency, Job, Review, Run, Video
from .pod import PodCoordinator, initial_result
from .settings import Settings
from .storage import S3Storage
from .video_probe import probe_mp4
from .worker import TERMINAL, EnrichmentWorker


class JobRequest(BaseModel):
    source_video_id: str
    analysis_profile_id: str


class RunRequest(BaseModel):
    analysis_profile_id: str


class ReviewRequest(BaseModel):
    run_id: str
    report_revision: int | None = None
    decision: str
    note: str = ""
    expected_review_revision: int = Field(ge=0)


class WorkerRegistration(BaseModel):
    pod_id: str
    worker_instance_id: str
    started_at: datetime
    models: dict


class WorkerHeartbeat(BaseModel):
    status: str
    gpu_memory_used_bytes: int | None = None
    active_run_id: str | None = None
    processed_pts: float | None = None
    sent_at: datetime


class EventRegistration(BaseModel):
    schema_version: str
    event_id: str
    sequence_number: int = Field(ge=0)
    worker_instance_id: str
    start_seconds: float
    end_seconds: float
    manifest_key: str
    manifest_sha256: str
    detected_at: datetime


class RunCompletion(BaseModel):
    worker_instance_id: str
    manifest_key: str
    manifest_sha256: str


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _error(status: int, code: str, message: str, details=None) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {
        "code": code, "message": message, "retryable": status >= 500, "details": details}})


def _cursor(row) -> str:
    raw = json.dumps([row.created_at.isoformat(), row.id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _page(query, model, cursor: str | None):
    if cursor:
        try:
            stamp, row_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            created = datetime.fromisoformat(stamp)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise _error(400, "INVALID_REQUEST", "Invalid cursor") from exc
        query = query.where(or_(model.created_at < created,
                                and_(model.created_at == created, model.id < row_id)))
    return query.order_by(model.created_at.desc(), model.id.desc())


def _idempotency(db, actor: str, route: str, key: str, payload: dict, response: dict | None = None):
    lookup = hashlib.sha256(f"{actor}:{route}:{key}".encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    found = db.get(Idempotency, lookup)
    if found:
        if found.request_hash != digest:
            raise _error(409, "IDEMPOTENCY_KEY_REUSED", "Key was used with different content")
        return found.response
    if response is not None:
        db.add(Idempotency(id=lookup, request_hash=digest, response=response))
    return None


def create_app(settings: Settings | None = None, *, sessions=None, storage=None,
               gemini=None, video_probe=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.app_api_key:
        raise RuntimeError("APP_API_KEY must be configured")
    sessions = sessions or make_session_factory(settings.database_url)
    app = FastAPI(title="CCTV Accident Detector API")
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.storage = storage
    app.state.gemini = gemini
    probe = video_probe or probe_mp4

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = _id("req")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        payload = exc.detail if isinstance(exc.detail, dict) and "error" in exc.detail else {
            "error": {"code": "http_error", "message": str(exc.detail), "retryable": False}}
        return JSONResponse(status_code=exc.status_code,
                            content={**payload, "request_id": request.state.request_id})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_FAILED",
                            "message": "Request does not match the API schema", "retryable": False,
                            "details": None}, "request_id": request.state.request_id})

    def auth(authorization: str | None = Header(default=None), x_actor_id: str | None = Header(default=None)) -> str:
        token = authorization.removeprefix("Bearer ") if authorization else ""
        if not hmac.compare_digest(token, settings.app_api_key):
            raise _error(401, "AUTHENTICATION_REQUIRED", "Valid bearer token required")
        # This identity is only suitable for restricted team demos, not public user authentication.
        return x_actor_id or "team-demo"

    def pod_auth(authorization: str | None = Header(default=None)) -> None:
        token = authorization.removeprefix("Bearer ") if authorization else ""
        if not settings.pod_worker_token or not hmac.compare_digest(token, settings.pod_worker_token):
            raise _error(401, "AUTHENTICATION_REQUIRED", "Valid Pod token required")

    def get_storage():
        if app.state.storage is None:
            app.state.storage = S3Storage(settings.s3_bucket, endpoint_url=settings.s3_endpoint_url,
                                          region_name=settings.aws_region)
        return app.state.storage

    def get_enrichment_worker():
        if app.state.gemini is None:
            app.state.gemini = GeminiVLM(settings.gemini_api_key, settings.gemini_model)
        return EnrichmentWorker(sessions, get_storage(), app.state.gemini, settings)

    app.state.get_enrichment_worker = get_enrichment_worker

    def coordinator():
        return PodCoordinator(sessions, get_storage(), settings)

    def video_payload(video: Video, *, include_hash: bool = False) -> dict:
        value = {"source_video_id": video.id, "file_name": video.filename,
                 "content_type": video.content_type, "size_bytes": video.size_bytes,
                 "duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                 "recorded_at": video.recorded_at, "created_at": video.created_at}
        if include_hash:
            value.update(upload_status="ready", sha256=video.sha256)
        return value

    def pod_call(callback, *args):
        try:
            return callback(*args)
        except ValueError as exc:
            raise _error(409, "POD_CONTRACT_CONFLICT", "Pod request conflicts with run state") from exc

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/videos", status_code=201)
    def upload_video(
        file: UploadFile = File(...), camera_id: str | None = Form(None),
        recorded_at: datetime | None = Form(None), idempotency_key: str = Header(..., alias="Idempotency-Key"),
        actor: str = Depends(auth),
    ):
        if not file.filename or not file.filename.lower().endswith(".mp4"):
            raise _error(415, "VIDEO_FORMAT_UNSUPPORTED", "Only MP4 files are accepted")
        if not 0 < len(idempotency_key) <= 200:
            raise _error(422, "VALIDATION_FAILED", "Invalid Idempotency-Key")
        data = file.file.read(settings.max_upload_bytes + 1)
        if not data or len(data) > settings.max_upload_bytes:
            raise _error(413, "VIDEO_TOO_LARGE", "Video is empty or too large")
        if b"ftyp" not in data[:16]:
            raise _error(415, "VIDEO_FORMAT_UNSUPPORTED", "Only MP4 files are accepted")
        payload = {"sha256": hashlib.sha256(data).hexdigest(), "camera_id": camera_id,
                   "recorded_at": recorded_at.isoformat() if recorded_at else None}
        with sessions.begin() as db:
            old = _idempotency(db, actor, "POST /videos", idempotency_key, payload)
            if old:
                return old
        try:
            duration = probe(data)
        except (ValueError, OSError) as exc:
            raise _error(422, "VIDEO_INVALID", "Unable to read video metadata") from exc
        video_id = _id("video")
        key = f"videos/{video_id}/original.mp4"
        try:
            obj = get_storage().put_video(key, BytesIO(data), settings.max_upload_bytes)
        except ValueError as exc:
            raise _error(413 if "oversized" in str(exc) else 415,
                         "VIDEO_TOO_LARGE" if "oversized" in str(exc) else "VIDEO_FORMAT_UNSUPPORTED",
                         "Unable to store video") from exc
        with sessions.begin() as db:
            video = Video(id=video_id, filename=file.filename[:255], s3_key=key, sha256=obj.sha256,
                          size_bytes=obj.size, content_type="video/mp4", duration_seconds=duration,
                          camera_id=camera_id, recorded_at=recorded_at)
            db.add(video)
            db.flush()
            db.add(Asset(id=f"source-{video_id}", run_id=None, s3_key=key, kind="original",
                         sha256=obj.sha256, mime_type="video/mp4"))
            response = video_payload(video, include_hash=True)
            response = json.loads(json.dumps(response, default=str))
            _idempotency(db, actor, "POST /videos", idempotency_key, payload, response)
        return response

    @app.get("/api/v1/videos")
    def list_videos(cursor: str | None = None, limit: int = Query(20, ge=1, le=100), actor: str = Depends(auth)):
        with sessions() as db:
            rows = list(db.scalars(_page(select(Video), Video, cursor).limit(limit + 1)))
            return {"items": [video_payload(v) for v in rows[:limit]],
                    "next_cursor": _cursor(rows[limit - 1]) if len(rows) > limit else None}

    @app.get("/api/v1/analysis-profiles")
    def analysis_profiles(actor: str = Depends(auth)):
        return {"items": [{"analysis_profile_id": settings.analysis_profile_id,
                           "display_name": "기본 사고 의심 분석",
                           "description": "X3D-S 후보 탐색과 YOLO11s 객체 정보를 제공합니다.",
                           "is_default": True, "enabled": True}]}

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(req: JobRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        with sessions.begin() as db:
            old = _idempotency(db, actor, "POST /jobs", idempotency_key, req.model_dump())
            if old:
                return old
            if req.analysis_profile_id != settings.analysis_profile_id:
                raise _error(422, "PROFILE_NOT_FOUND", "Unknown analysis profile")
            video = db.get(Video, req.source_video_id)
            if video is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "Video not found")
            job_id, run_id = _id("job"), _id("run")
            db.add(Job(id=job_id, video_id=req.source_video_id, active_run_id=run_id))
            run = Run(id=run_id, job_id=job_id, profile_id=req.analysis_profile_id,
                      result=initial_result(video))
            db.add(run)
            db.flush()
            response = {"job_id": job_id, "run_id": run_id, "status": run.status,
                        "detection_outcome": run.outcome, "created_at": run.created_at.isoformat()}
            _idempotency(db, actor, "POST /jobs", idempotency_key, req.model_dump(), response)
            return response

    @app.get("/api/v1/jobs")
    def list_jobs(cursor: str | None = None, limit: int = Query(20, ge=1, le=100),
                  status: str | None = None, source_video_id: str | None = None,
                  actor: str = Depends(auth)):
        with sessions() as db:
            query = select(Job).join(Run, Job.active_run_id == Run.id)
            if status:
                query = query.where(Run.status == status)
            if source_video_id:
                query = query.where(Job.video_id == source_video_id)
            rows = list(db.scalars(_page(query, Job, cursor).limit(limit + 1)))
            items = []
            for job in rows[:limit]:
                run = db.get(Run, job.active_run_id)
                items.append({"job_id": job.id, "active_run_id": run.id, "source_video_id": job.video_id,
                              "status": run.status, "detection_outcome": run.outcome,
                              "candidate_count": len((run.result or {}).get("candidates", [])),
                              "created_at": job.created_at, "updated_at": run.updated_at})
            return {"items": items, "next_cursor": _cursor(rows[limit - 1]) if len(rows) > limit else None}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str, run_id: str | None = None, actor: str = Depends(auth)):
        with sessions() as db:
            job = db.get(Job, job_id)
            if not job:
                raise _error(404, "RESOURCE_NOT_FOUND", "Job not found")
            run = db.get(Run, run_id or job.active_run_id)
            if not run or run.job_id != job.id:
                raise _error(404, "RESOURCE_NOT_FOUND", "Run not found")
            video = db.get(Video, job.video_id)
            result = run.result or {}
            return {"schema_version": "service-draft-v0.2", "is_demo": False,
                    "job_id": job.id, "run_id": run.id, "source_video_id": video.id,
                    "status": run.status, "detection_outcome": run.outcome,
                    "created_at": run.created_at, "updated_at": run.updated_at,
                    "video": result.get("video") or {"duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                        "recorded_at": video.recorded_at, "original_asset_id": f"source-{video.id}"},
                    "coverage": result.get("coverage"), "models": result.get("models"),
                    "stages": result.get("stages"), "candidates": result.get("candidates", []),
                    "errors": [run.error] if run.error else result.get("errors", [])}

    @app.post("/api/v1/jobs/{job_id}/runs", status_code=202)
    def rerun(job_id: str, req: RunRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        with sessions.begin() as db:
            old = _idempotency(db, actor, f"POST /jobs/{job_id}/runs", idempotency_key, req.model_dump())
            if old:
                return old
            job = db.get(Job, job_id)
            if not job:
                raise _error(404, "RESOURCE_NOT_FOUND", "Job not found")
            if db.get(Run, job.active_run_id).status not in TERMINAL:
                raise _error(409, "RUN_ALREADY_ACTIVE", "Current run has not finished")
            if req.analysis_profile_id != settings.analysis_profile_id:
                raise _error(422, "PROFILE_NOT_FOUND", "Unknown analysis profile")
            run_id = _id("run")
            run = Run(id=run_id, job_id=job.id, profile_id=req.analysis_profile_id,
                      result=initial_result(db.get(Video, job.video_id)))
            db.add(run)
            job.active_run_id = run_id
            db.flush()
            response = {"job_id": job.id, "run_id": run_id, "status": run.status,
                        "detection_outcome": run.outcome, "created_at": run.created_at.isoformat()}
            _idempotency(db, actor, f"POST /jobs/{job_id}/runs", idempotency_key, req.model_dump(), response)
            return response

    @app.get("/api/v1/assets/{asset_id}/url")
    def asset_url(asset_id: str, actor: str = Depends(auth)):
        with sessions() as db:
            asset = db.get(Asset, asset_id)
            if not asset:
                raise _error(404, "RESOURCE_NOT_FOUND", "Asset not found")
            return {"asset_id": asset.id, "url": get_storage().url(asset.s3_key),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "content_type": asset.mime_type}

    @app.post("/api/v1/events/{event_id}/reviews", status_code=201)
    def create_review(event_id: str, req: ReviewRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        if req.decision not in {"confirmed_accident", "not_accident", "uncertain"}:
            raise _error(422, "VALIDATION_FAILED", "Unknown review decision")
        with sessions.begin() as db:
            old = _idempotency(db, actor, f"POST /events/{event_id}/reviews", idempotency_key, req.model_dump())
            if old:
                return old
            event = db.get(Event, event_id)
            if not event or event.run_id != req.run_id:
                raise _error(404, "RESOURCE_NOT_FOUND", "Event not found")
            current = db.scalars(select(Review).where(Review.event_id == event_id).order_by(Review.revision.desc())).first()
            revision = current.revision if current else 0
            if revision != req.expected_review_revision:
                raise _error(409, "REVIEW_REVISION_CONFLICT", "Review revision changed",
                             {"current_review_revision": revision})
            report = event.data.get("report")
            if req.report_revision is not None and (not report or report["revision"] != req.report_revision):
                raise _error(409, "REVIEW_REVISION_CONFLICT", "Report revision changed")
            review = Review(id=_id("review"), event_id=event_id, run_id=req.run_id,
                            report_revision=req.report_revision, revision=revision + 1,
                            decision=req.decision, note=req.note, reviewer_id=actor)
            db.add(review)
            db.flush()
            event_data = dict(event.data)
            event_data["human_review"] = {"status": req.decision, "review_revision": review.revision,
                                          "review_id": review.id, "report_revision": req.report_revision,
                                          "note": req.note or None}
            event.data = event_data
            run = db.get(Run, event.run_id)
            if run.result:
                result = dict(run.result)
                result["candidates"] = [event_data if item["event_id"] == event_id else item
                                        for item in result.get("candidates", [])]
                run.result = result
            response = {"review_id": review.id, "event_id": event_id, "run_id": req.run_id,
                        "report_revision": req.report_revision, "decision": req.decision,
                        "note": req.note or None, "review_revision": review.revision,
                        "reviewed_at": review.created_at.isoformat()}
            _idempotency(db, actor, f"POST /events/{event_id}/reviews", idempotency_key, req.model_dump(), response)
            return response

    @app.get("/api/v1/events/{event_id}/reviews")
    def list_reviews(event_id: str, cursor: str | None = None,
                     limit: int = Query(20, ge=1, le=100), actor: str = Depends(auth)):
        with sessions() as db:
            if db.get(Event, event_id) is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "Event not found")
            rows = list(db.scalars(_page(select(Review).where(Review.event_id == event_id),
                                         Review, cursor).limit(limit + 1)))
            return {"items": [{"review_id": r.id, "event_id": r.event_id,
                               "review_revision": r.revision, "run_id": r.run_id,
                               "report_revision": r.report_revision, "decision": r.decision,
                               "note": r.note or None, "reviewed_at": r.created_at} for r in rows[:limit]],
                    "next_cursor": _cursor(rows[limit - 1]) if len(rows) > limit else None}

    @app.post("/internal/v1/workers/register", status_code=201)
    def register_worker(req: WorkerRegistration, _: None = Depends(pod_auth)):
        return pod_call(coordinator().register, req.model_dump())

    @app.post("/internal/v1/workers/{worker_id}/heartbeat")
    def worker_heartbeat(worker_id: str, req: WorkerHeartbeat, _: None = Depends(pod_auth)):
        return pod_call(coordinator().heartbeat, worker_id, req.model_dump())

    @app.post("/internal/v1/workers/{worker_id}/claim")
    def claim_run(worker_id: str, _: None = Depends(pod_auth)):
        assignment = pod_call(coordinator().claim, worker_id)
        return {"assignment": assignment}

    @app.post("/internal/v1/runs/{run_id}/events", status_code=201)
    def register_event(run_id: str, req: EventRegistration, _: None = Depends(pod_auth)):
        return pod_call(coordinator().event, run_id, req.model_dump())

    @app.post("/internal/v1/runs/{run_id}/complete")
    def complete_run(run_id: str, req: RunCompletion, _: None = Depends(pod_auth)):
        return pod_call(coordinator().complete, run_id, req.model_dump())

    return app
