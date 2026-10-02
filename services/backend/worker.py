"""CPU-only Gemini enrichment for candidates produced by Modal inference."""

import hashlib
import logging
from uuid import uuid4

from sqlalchemy import select

from .models import Asset, Event, Report, Run, now

log = logging.getLogger(__name__)
TERMINAL = {"completed", "partial", "failed"}


class EnrichmentWorker:
    def __init__(self, sessions, storage, gemini, settings, rag=None):
        """DB, 근거 저장소, Gemini 클라이언트와 용량 제한을 설정한다."""
        self.sessions, self.storage, self.gemini, self.settings = sessions, storage, gemini, settings
        self.rag = rag

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
            recorded_at = ((run.result or {}).get("video") or {}).get("recorded_at")
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
        retrieval = {"status": "insufficient_evidence", "query": None,
                     "corpus_version": None, "retrieval_version": None, "citations": []}
        report["generation_status"] = "completed"
        report["agencies"] = []
        stage_errors = []
        if vlm["status"] == "failed":
            retrieval.update(status="skipped", reason_code="vlm_unavailable")
            report["generation_status"] = "skipped"
        elif self.rag is not None:
            try:
                retrieval = self.rag.retrieve(vlm["rag_input"], recorded_at=recorded_at)
            except Exception as exc:
                log.exception("RAG retrieval failed for event %s", event_id)
                retrieval.update(status="failed", reason_code=type(exc).__name__)
                stage_errors.append({"stage": "rag", "code": type(exc).__name__,
                    "message": "문서 검색 실패: 인덱스·설정·연결을 확인하세요.", "retryable": True})
                report.update(status="partial", generation_status="skipped",
                              limitations=["문서 검색에 실패했습니다.", *vlm.get("uncertainties", [])])
            if retrieval["status"] != "failed":
                try:
                    final = self.rag.generate_report(vlm["rag_input"], vlm, retrieval,
                        model=vlm_config.get("model") or self.settings.gemini_model)
                    report.update(text=final["summary"], agencies=final["agencies"],
                        structured=final, limitations=[*vlm.get("uncertainties", []), *final["limitations"],
                            "자료 현행성 및 피해·법적 책임은 확정되지 않았습니다."])
                    report["citation_document_ids"] = list(dict.fromkeys(
                        c["document_id"] for c in retrieval["citations"]))
                    report["citation_chunk_ids"] = [c["chunk_id"] for c in retrieval["citations"]]
                    report["corpus_version"] = retrieval["corpus_version"]
                    if retrieval["status"] == "insufficient_evidence":
                        report["limitations"].append("관련 문서 근거가 부족해 기관을 선정하지 않았습니다.")
                except Exception as exc:
                    log.exception("Report generation failed for event %s", event_id)
                    report.update(status="partial", generation_status="failed",
                        limitations=["최종 리포트 JSON 생성·검증에 실패했습니다.", *vlm.get("uncertainties", [])])
                    stage_errors.append({"stage": "report", "code": type(exc).__name__,
                        "message": "리포트 생성·검증 실패: 영상 관찰과 검색 근거를 확인하세요.", "retryable": True})
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
            event_data["retrieval"] = retrieval
            event_data["report"] = report
            event.data = event_data
            db.add(Report(id=report["report_id"], event_id=event_id,
                          revision=report["revision"], data=report))
            run = db.get(Run, event.run_id)
            result = dict(run.result)
            result["candidates"] = [event_data if item["event_id"] == event_id else item
                                    for item in result["candidates"]]
            stages = dict(result["stages"])
            result["errors"] = [*(result.get("errors") or []), *stage_errors]
            failures = any(item.get("vlm", {}).get("status") == "failed"
                           for item in result["candidates"])
            pending = any("vlm" not in item for item in result["candidates"])
            stages["vlm"] = {"status": "running" if pending else "failed" if failures else "completed",
                              "reason_code": "gemini_error" if failures else None}
            for name in ("rag", "report"):
                values = [((item.get("retrieval") or {}).get("status", "pending") if name == "rag"
                    else (item.get("report") or {}).get("generation_status", "pending"))
                    for item in result["candidates"]]
                status = next((s for s in ("failed", "running", "pending", "insufficient_evidence", "completed")
                               if s in values), "skipped")
                stages[name] = {"status": status, "reason_code": (
                    f"{name}_error" if status == "failed" else "vlm_unavailable" if status == "skipped"
                    else "corpus_not_configured" if self.rag is None and status == "insufficient_evidence" else None)}
            result["stages"] = stages
            run.result = result
            if run.status == "enriching" and not pending:
                coverage = result["coverage"]
                run.status = "partial" if (failures or stages["rag"]["status"] == "failed"
                    or stages["report"]["status"] == "failed"
                    or coverage["unclassified_windows"] or coverage["pending_windows"]) else "completed"
        return True
