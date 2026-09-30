import hashlib
import hmac
import json
import base64
import time
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
from .gemini_vlm import DEFAULT_ANALYSIS_PROMPT, PROMPT_PRESETS, GeminiVLM
from .models import AnalysisProfile, Asset, Event, Idempotency, Job, Review, Run, Video
from .modal_service import ModalGateway, ModalWorker
from .result_state import initial_result
from .settings import Settings
from .storage import S3Storage
from .video_probe import probe_mp4
from .worker import TERMINAL, EnrichmentWorker


class VlmOptions(BaseModel):
    model: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:/-]+$")
    prompt: str = Field(default="", max_length=12000)
    prompt_mode: str = Field(default="prepend", pattern=r"^(prepend|replace)$")


class VlmCheckRequest(BaseModel):
    model: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:/-]+$")


class JobRequest(BaseModel):
    source_video_id: str
    analysis_profile_id: str
    vlm: VlmOptions | None = None
    defer_vlm: bool = False


class RunRequest(BaseModel):
    analysis_profile_id: str
    vlm: VlmOptions | None = None
    defer_vlm: bool = False


class ReviewRequest(BaseModel):
    run_id: str
    report_revision: int | None = None
    decision: str
    note: str = ""
    expected_review_revision: int = Field(ge=0)


def _id(prefix: str) -> str:
    """접두사가 포함된 새 리소스 ID를 생성한다."""
    return f"{prefix}-{uuid4().hex}"


def _error(status: int, code: str, message: str, details=None) -> HTTPException:
    """공개 API의 공통 오류 형식으로 HTTP 예외를 만든다."""
    return HTTPException(status_code=status, detail={"error": {
        "code": code, "message": message, "retryable": status >= 500, "details": details}})


def _cursor(row) -> str:
    """생성 시각과 ID를 목록 페이지네이션 커서로 인코딩한다."""
    raw = json.dumps([row.created_at.isoformat(), row.id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _page(query, model, cursor: str | None):
    """커서 이후의 행을 최신순으로 조회하도록 쿼리를 구성한다."""
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
    """요청 키의 기존 응답을 찾거나 새 응답을 저장하고 본문 변경을 거부한다."""
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
               gemini=None, video_probe=None, modal_gateway=None) -> FastAPI:
    """의존성을 구성하고 공개 API 및 GPU 추론 작업 서비스를 등록한다."""
    settings = settings or Settings.from_env()
    if not settings.app_api_key:
        raise RuntimeError("APP_API_KEY must be configured")
    sessions = sessions or make_session_factory(settings.database_url)
    app = FastAPI(title="CCTV Accident Detector API")
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.storage = storage
    app.state.gemini = gemini
    app.state.modal_gateway = modal_gateway
    probe = video_probe or probe_mp4

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """요청별 추적 ID를 생성하고 응답 헤더에 추가한다."""
        request.state.request_id = _id("req")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        """HTTP 예외를 공통 오류 본문과 요청 ID로 변환한다."""
        payload = exc.detail if isinstance(exc.detail, dict) and "error" in exc.detail else {
            "error": {"code": "http_error", "message": str(exc.detail), "retryable": False}}
        return JSONResponse(status_code=exc.status_code,
                            content={**payload, "request_id": request.state.request_id})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """요청 스키마 검증 오류를 공통 422 응답으로 변환한다."""
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_FAILED",
                            "message": "Request does not match the API schema", "retryable": False,
                            "details": None}, "request_id": request.state.request_id})

    def auth(authorization: str | None = Header(default=None), x_actor_id: str | None = Header(default=None)) -> str:
        """공개 API의 bearer 토큰을 확인하고 데모용 행위자 ID를 반환한다."""
        token = authorization.removeprefix("Bearer ") if authorization else ""
        if not hmac.compare_digest(token, settings.app_api_key):
            raise _error(401, "AUTHENTICATION_REQUIRED", "Valid bearer token required")
        # This identity is only suitable for restricted team demos, not public user authentication.
        return x_actor_id or "team-demo"

    def get_storage():
        """주입된 저장소를 사용하거나 S3 클라이언트를 지연 생성한다."""
        if app.state.storage is None:
            app.state.storage = S3Storage(settings.s3_bucket, endpoint_url=settings.s3_endpoint_url,
                                          region_name=settings.aws_region)
        return app.state.storage

    def get_enrichment_worker():
        """Gemini 클라이언트와 저장소를 연결한 후처리 worker를 만든다."""
        if app.state.gemini is None:
            app.state.gemini = GeminiVLM(settings.gemini_api_key, settings.gemini_model)
        return EnrichmentWorker(sessions, get_storage(), app.state.gemini, settings)

    app.state.get_enrichment_worker = get_enrichment_worker

    def get_modal_worker():
        """Modal 제출·결과 회수 작업자를 현재 저장소에 연결한다."""
        if app.state.modal_gateway is None:
            app.state.modal_gateway = ModalGateway(settings)
        return ModalWorker(sessions, get_storage(), app.state.modal_gateway,
                           settings.s3_key_prefix)

    app.state.get_modal_worker = get_modal_worker

    def video_payload(video: Video, *, include_hash: bool = False) -> dict:
        """영상 DB 행을 공개 API의 영상 응답 형식으로 변환한다."""
        value = {"source_video_id": video.id, "file_name": video.filename,
                 "content_type": video.content_type, "size_bytes": video.size_bytes,
                 "duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                 "recorded_at": video.recorded_at, "created_at": video.created_at}
        if include_hash:
            value.update(upload_status="ready", sha256=video.sha256)
        return value

    def profile_payload(profile: AnalysisProfile) -> dict:
        return {"analysis_profile_id": profile.id, "display_name": profile.display_name,
                "description": profile.description, "is_default": False,
                "enabled": profile.enabled, "models": profile.models,
                "created_at": profile.created_at}

    def profile_snapshot(db, profile_id: str) -> dict:
        if profile_id == settings.analysis_profile_id:
            return {"id": profile_id, "source": "modal_secret"}
        profile = db.get(AnalysisProfile, profile_id)
        if profile is None or not profile.enabled:
            raise _error(422, "PROFILE_NOT_FOUND", "Unknown analysis profile")
        return {"id": profile.id, "source": "registered", "models": profile.models}

    @app.get("/health")
    def health():
        """프로세스의 기본 HTTP 응답 상태를 반환한다."""
        return {"status": "ok"}

    @app.post("/api/v1/videos", status_code=201)
    def upload_video(
        file: UploadFile = File(...), camera_id: str | None = Form(None),
        recorded_at: datetime | None = Form(None), idempotency_key: str = Header(..., alias="Idempotency-Key"),
        actor: str = Depends(auth),
    ):
        """MP4를 검증해 S3에 저장하고 영상 및 원본 asset을 등록한다."""
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
        key = f"{settings.s3_key_prefix}videos/{video_id}/original.mp4"
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
        """등록된 영상을 커서 기반으로 조회한다."""
        with sessions() as db:
            rows = list(db.scalars(_page(select(Video), Video, cursor).limit(limit + 1)))
            return {"items": [video_payload(v) for v in rows[:limit]],
                    "next_cursor": _cursor(rows[limit - 1]) if len(rows) > limit else None}

    @app.get("/api/v1/analysis-profiles")
    def analysis_profiles(actor: str = Depends(auth)):
        """현재 사용 가능한 분석 프로필을 반환한다."""
        legacy = {"analysis_profile_id": settings.analysis_profile_id,
                  "display_name": "기본 사고 의심 분석",
                  "description": "Modal Secret의 X3D-S·YOLO 가중치를 사용합니다.",
                  "is_default": True, "enabled": True, "models": None}
        with sessions() as db:
            rows = db.scalars(select(AnalysisProfile).where(AnalysisProfile.enabled.is_(True))
                              .order_by(AnalysisProfile.created_at.desc())).all()
            return {"items": [legacy, *(profile_payload(row) for row in rows)]}

    @app.post("/api/v1/analysis-profiles", status_code=201)
    def create_analysis_profile(
        display_name: str = Form(..., min_length=1, max_length=200),
        description: str = Form("", max_length=2000),
        accident_family: str = Form("X3D-S", min_length=1, max_length=80),
        object_family: str = Form("YOLO11", min_length=1, max_length=80),
        accident_weights: UploadFile = File(...), object_weights: UploadFile = File(...),
        actor: str = Depends(auth),
    ):
        """두 모델 가중치를 S3에 올리고 선택 가능한 불변 프로필을 등록한다."""
        allowed_suffixes = (".pt", ".pth")
        if accident_family != "X3D-S" or object_family != "YOLO11":
            raise _error(422, "MODEL_FAMILY_NOT_SUPPORTED",
                         "Current pipeline supports X3D-S and Ultralytics YOLO11 weights")
        if not (accident_weights.filename or "").lower().endswith(allowed_suffixes):
            raise _error(422, "INVALID_MODEL_WEIGHT", "Accident weight must be .pt or .pth")
        if not (object_weights.filename or "").lower().endswith(allowed_suffixes):
            raise _error(422, "INVALID_MODEL_WEIGHT", "Object weight must be .pt or .pth")
        profile_id = _id("profile")
        prefix = f"{settings.s3_key_prefix}model-profiles/{profile_id}/"
        storage_service = get_storage()
        uploaded_keys = []
        try:
            accident = storage_service.put_model_weight(
                prefix + "accident.pt", accident_weights.file, settings.max_model_weight_bytes)
            uploaded_keys.append(accident.key)
            objects = storage_service.put_model_weight(
                prefix + "objects.pt", object_weights.file, settings.max_model_weight_bytes)
            uploaded_keys.append(objects.key)
            models = {
                "accident": {"family": accident_family, "weights": {
                    "bucket": storage_service.bucket, "key": accident.key,
                    "sha256": accident.sha256, "size_bytes": accident.size,
                    "file_name": accident_weights.filename}},
                "objects": {"family": object_family, "weights": {
                    "bucket": storage_service.bucket, "key": objects.key,
                    "sha256": objects.sha256, "size_bytes": objects.size,
                    "file_name": object_weights.filename}},
            }
            with sessions.begin() as db:
                profile = AnalysisProfile(id=profile_id, display_name=display_name.strip(),
                                          description=description.strip(), models=models)
                db.add(profile)
                db.flush()
                response = profile_payload(profile)
            return response
        except ValueError as exc:
            for key in uploaded_keys:
                storage_service.delete(key)
            raise _error(422, "INVALID_MODEL_WEIGHT", str(exc)) from exc
        except Exception:
            for key in uploaded_keys:
                storage_service.delete(key)
            raise

    @app.get("/api/v1/vlm-options")
    def vlm_options(actor: str = Depends(auth)):
        """작업별 VLM 설정 화면에 사용할 허용 모델과 기본값을 반환한다."""
        models = settings.gemini_models or (settings.gemini_model,)
        return {"models": list(models), "default_model": settings.gemini_model,
                "prompt_default": DEFAULT_ANALYSIS_PROMPT,
                "prompt_presets": list(PROMPT_PRESETS),
                "default_prompt_preset": "version1",
                "prompt_modes": ["replace", "prepend"],
                "default_prompt_mode": "replace"}

    @app.post("/api/v1/vlm-options/check")
    def check_vlm(req: VlmCheckRequest, actor: str = Depends(auth)):
        """허용된 Gemini 모델에 작은 요청을 보내 현재 API 응답 상태를 확인한다."""
        if req.model not in (settings.gemini_models or (settings.gemini_model,)):
            raise _error(422, "VLM_MODEL_NOT_ALLOWED", "Gemini model is not enabled")
        started = time.perf_counter()
        try:
            result = get_enrichment_worker().gemini.check(req.model)
        except Exception as exc:
            return {"available": False, "model": req.model,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "error_code": type(exc).__name__}
        return {"available": True, **result,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "error_code": None}

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(req: JobRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        """등록된 영상의 분석 작업과 첫 실행을 대기 상태로 만든다."""
        with sessions.begin() as db:
            old = _idempotency(db, actor, "POST /jobs", idempotency_key, req.model_dump())
            if old:
                return old
            selected_profile = profile_snapshot(db, req.analysis_profile_id)
            vlm = req.vlm or VlmOptions(model=settings.gemini_model)
            if vlm.model not in (settings.gemini_models or (settings.gemini_model,)):
                raise _error(422, "VLM_MODEL_NOT_ALLOWED", "Gemini model is not enabled")
            video = db.get(Video, req.source_video_id)
            if video is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "Video not found")
            job_id, run_id = _id("job"), _id("run")
            db.add(Job(id=job_id, video_id=req.source_video_id, active_run_id=run_id))
            vlm_config = vlm.model_dump()
            vlm_config["manual_start"] = req.defer_vlm
            run = Run(id=run_id, job_id=job_id, profile_id=req.analysis_profile_id,
                      result=initial_result(video, {"vlm": vlm_config,
                                                    "analysis_profile": selected_profile}))
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
        """상태와 영상 ID로 필터링한 분석 작업 목록을 조회한다."""
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
                              "status": "queued" if run.status == "dispatching" else run.status,
                              "detection_outcome": run.outcome,
                              "candidate_count": len((run.result or {}).get("candidates", [])),
                              "created_at": job.created_at, "updated_at": run.updated_at})
            return {"items": items, "next_cursor": _cursor(rows[limit - 1]) if len(rows) > limit else None}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str, run_id: str | None = None, actor: str = Depends(auth)):
        """지정한 실행 또는 현재 실행의 단계·후보·결과를 반환한다."""
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
                    "status": "queued" if run.status == "dispatching" else run.status,
                    "detection_outcome": run.outcome,
                    "created_at": run.created_at, "updated_at": run.updated_at,
                    "video": result.get("video") or {"duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                        "recorded_at": video.recorded_at, "original_asset_id": f"source-{video.id}"},
                    "coverage": result.get("coverage"), "models": result.get("models"),
                    "execution_config": result.get("execution_config", {}),
                    "stages": result.get("stages"), "candidates": result.get("candidates", []),
                    "errors": [run.error] if run.error else result.get("errors", [])}

    @app.post("/api/v1/jobs/{job_id}/runs", status_code=202)
    def rerun(job_id: str, req: RunRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        """종료된 작업에 새 분석 실행을 만들고 활성 실행으로 지정한다."""
        with sessions.begin() as db:
            old = _idempotency(db, actor, f"POST /jobs/{job_id}/runs", idempotency_key, req.model_dump())
            if old:
                return old
            job = db.get(Job, job_id)
            if not job:
                raise _error(404, "RESOURCE_NOT_FOUND", "Job not found")
            if db.get(Run, job.active_run_id).status not in TERMINAL:
                raise _error(409, "RUN_ALREADY_ACTIVE", "Current run has not finished")
            selected_profile = profile_snapshot(db, req.analysis_profile_id)
            vlm = req.vlm or VlmOptions(model=settings.gemini_model)
            if vlm.model not in (settings.gemini_models or (settings.gemini_model,)):
                raise _error(422, "VLM_MODEL_NOT_ALLOWED", "Gemini model is not enabled")
            run_id = _id("run")
            vlm_config = vlm.model_dump()
            vlm_config["manual_start"] = req.defer_vlm
            run = Run(id=run_id, job_id=job.id, profile_id=req.analysis_profile_id,
                      result=initial_result(db.get(Video, job.video_id),
                                            {"vlm": vlm_config,
                                             "analysis_profile": selected_profile}))
            db.add(run)
            job.active_run_id = run_id
            db.flush()
            response = {"job_id": job.id, "run_id": run_id, "status": run.status,
                        "detection_outcome": run.outcome, "created_at": run.created_at.isoformat()}
            _idempotency(db, actor, f"POST /jobs/{job_id}/runs", idempotency_key, req.model_dump(), response)
            return response

    @app.get("/api/v1/assets/{asset_id}/url")
    def asset_url(asset_id: str, actor: str = Depends(auth)):
        """원본 영상이나 근거 asset의 짧게 유효한 다운로드 URL을 발급한다."""
        with sessions() as db:
            asset = db.get(Asset, asset_id)
            if not asset:
                raise _error(404, "RESOURCE_NOT_FOUND", "Asset not found")
            return {"asset_id": asset.id, "url": get_storage().url(asset.s3_key),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "content_type": asset.mime_type}

    @app.post("/api/v1/events/{event_id}/reviews", status_code=201)
    def create_review(event_id: str, req: ReviewRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"), actor: str = Depends(auth)):
        """검토 버전을 확인하고 사람의 사고 판정과 메모를 저장한다."""
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
        """이벤트에 저장된 사람 검토 이력을 커서 기반으로 조회한다."""
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

    return app
