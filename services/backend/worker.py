"""CPU-only Gemini enrichment for candidates produced by Modal inference."""

import hashlib
import logging
from uuid import uuid4

from sqlalchemy import select

from .models import Asset, Event, Report, Run, now

log = logging.getLogger(__name__)
TERMINAL = {"completed", "partial", "failed"}


class EnrichmentWorker:
    def __init__(self, sessions, storage, gemini, settings):
        """DB, 근거 저장소, Gemini 클라이언트와 용량 제한을 설정한다."""
        self.sessions, self.storage, self.gemini, self.settings = sessions, storage, gemini, settings

    def tick(self) -> bool:
        """미처리 이벤트 하나를 Gemini로 보강하고 RAG·리포트 상태를 저장한다."""
        with self.sessions() as db:
            events = db.scalars(
                select(Event).join(Run, Event.run_id == Run.id)
                .where(Run.status.in_(("running", "enriching"))).order_by(Event.id)
            ).all()
            event_id = next((event.id for event in events if "vlm" not in event.data), None)
        if event_id is None:
            return False
        with self.sessions() as db:
            event = db.get(Event, event_id)
            event_data = dict(event.data)
            run = db.get(Run, event.run_id)
            vlm_config = ((run.result or {}).get("execution_config") or {}).get("vlm") or {}
            evidence = event_data["evidence"]
            ids = [evidence["clip_asset_id"]] if evidence.get("clip_asset_id") else []
            ids += [frame["asset_id"] for frame in evidence["frames"]]
            assets = [db.get(Asset, asset_id) for asset_id in ids]
        try:
            media, total = [], 0
            for asset in assets:
                limit = self.settings.max_gemini_clip_bytes if asset.kind == "clip" else 5_000_000
                blob = self.storage.get_bytes(asset.s3_key, limit)
                if hashlib.sha256(blob).hexdigest() != asset.sha256:
                    raise ValueError("evidence_sha256_mismatch")
                total += len(blob)
                if total > self.settings.max_gemini_clip_bytes:
                    raise ValueError("gemini_media_too_large")
                media.append((asset.id, asset.mime_type, blob))
            vlm = self.gemini.analyze(
                event_data,
                media,
                model=vlm_config.get("model"),
                prompt_override=vlm_config.get("prompt", ""),
                prompt_mode=vlm_config.get("prompt_mode", "prepend"),
            )
        except Exception as exc:
            log.exception("Gemini failed for event %s", event_id)
            error_message = str(exc).strip() or type(exc).__name__
            api_key = getattr(self.settings, "gemini_api_key", "")
            if api_key:
                error_message = error_message.replace(api_key, "[REDACTED]")
            vlm = {"status": "failed", "reason_code": type(exc).__name__, "summary": None,
                   "error_message": error_message[:1000],
                   "observations": [], "uncertainties": ["장면 설명 실패"]}
        report = {"report_id": f"report-{uuid4().hex}", "revision": 1,
                  "status": "partial" if vlm["status"] == "failed" else "completed",
                  "text": vlm.get("summary") or "장면 설명을 생성하지 못했습니다. 원본 근거를 확인하세요.",
                  "source_event_id": event_id, "evidence_asset_ids": ids,
                  "citation_document_ids": [],
                  "limitations": ["RAG 문서 원문이 아직 연결되지 않았습니다.",
                                  *vlm.get("uncertainties", [])],
                  "generated_at": now().isoformat()}
        with self.sessions.begin() as db:
            event = db.get(Event, event_id)
            if "vlm" in event.data:
                return True
            previous_report = db.scalars(
                select(Report).where(Report.event_id == event_id)
                .order_by(Report.revision.desc())
            ).first()
            report["revision"] = previous_report.revision + 1 if previous_report else 1
            event_data = dict(event.data)
            vlm_payload = dict(vlm)
            rag_input = vlm_payload.pop("rag_input", None)
            event_data["vlm"] = vlm_payload
            if rag_input:
                event_data["rag_input"] = rag_input
            event_data["retrieval"] = {"status": "insufficient_evidence", "query": None,
                                        "corpus_version": None, "retrieval_version": None,
                                        "citations": []}
            event_data["report"] = report
            event.data = event_data
            db.add(Report(id=report["report_id"], event_id=event_id,
                          revision=report["revision"], data=report))
            run = db.get(Run, event.run_id)
            result = dict(run.result)
            result["candidates"] = [event_data if item["event_id"] == event_id else item
                                    for item in result["candidates"]]
            stages = dict(result["stages"])
            failures = any(item.get("vlm", {}).get("status") == "failed"
                           for item in result["candidates"])
            pending = any("vlm" not in item for item in result["candidates"])
            stages["vlm"] = {"status": "running" if pending else "failed" if failures else "completed",
                              "reason_code": "gemini_error" if failures else None}
            stages["rag"] = {"status": "skipped" if failures else "insufficient_evidence",
                             "reason_code": "vlm_unavailable" if failures else "corpus_not_configured"}
            stages["report"] = {"status": "completed", "reason_code": None}
            result["stages"] = stages
            run.result = result
            if run.status == "enriching" and not pending:
                coverage = result["coverage"]
                run.status = "partial" if failures or coverage["unclassified_windows"] or coverage["pending_windows"] else "completed"
        return True
