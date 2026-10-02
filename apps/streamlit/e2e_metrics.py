"""Numeric summaries for the upload-to-VLM test page."""

from __future__ import annotations

from typing import Any


STATUS_CODES = {
    "queued": 0,
    "dispatching": 1,
    "running": 2,
    "awaiting_vlm": 3,
    "enriching": 3,
    "completed": 4,
    "partial": -1,
    "failed": -2,
}


def summarize_result(result: dict[str, Any]) -> dict[str, int | float]:
    """Reduce a job response to stable numeric E2E indicators."""
    coverage = result.get("coverage") or {}
    candidates = result.get("candidates") or []
    observations = [
        observation
        for candidate in candidates
        for observation in ((candidate.get("vlm") or {}).get("observations") or [])
    ]
    uncertainties = [
        uncertainty
        for candidate in candidates
        for uncertainty in ((candidate.get("vlm") or {}).get("uncertainties") or [])
    ]
    scores = [
        float(candidate["score"])
        for candidate in candidates
        if isinstance(candidate.get("score"), (int, float))
    ]
    vlm_completed = sum(
        (candidate.get("vlm") or {}).get("status") == "completed"
        for candidate in candidates
    )
    return {
        "status_code": STATUS_CODES.get(result.get("status"), -9),
        "scheduled_windows": int(coverage.get("scheduled_windows") or 0),
        "predicted_windows": int(coverage.get("predicted_windows") or 0),
        "unclassified_windows": int(coverage.get("unclassified_windows") or 0),
        "pending_windows": int(coverage.get("pending_windows") or 0),
        "candidate_count": len(candidates),
        "max_candidate_score": max(scores, default=0.0),
        "vlm_completed_count": vlm_completed,
        "vlm_observation_count": len(observations),
        "vlm_uncertainty_count": len(uncertainties),
        "rag_input_count": sum(bool(candidate.get("rag_input")) for candidate in candidates),
        "retrieval_completed_count": sum(
            (candidate.get("retrieval") or {}).get("status") == "completed" for candidate in candidates),
        "citation_count": sum(len((candidate.get("retrieval") or {}).get("citations") or [])
                              for candidate in candidates),
        "report_completed_count": sum(
            (candidate.get("report") or {}).get("generation_status") == "completed"
            and bool((candidate.get("report") or {}).get("structured")) for candidate in candidates),
        "agency_count": sum(len((candidate.get("report") or {}).get("agencies") or [])
                            for candidate in candidates),
        "error_count": len(result.get("errors") or []),
    }


def vlm_io_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Build inspectable per-candidate Gemini input metadata and parsed output."""
    config = ((result.get("execution_config") or {}).get("vlm") or {})
    records = []
    for candidate in result.get("candidates") or []:
        evidence = candidate.get("evidence") or {}
        asset_ids = ([evidence["clip_asset_id"]] if evidence.get("clip_asset_id") else [])
        asset_ids.extend(frame["asset_id"] for frame in evidence.get("frames") or [])
        vlm = candidate.get("vlm") or {}
        request = vlm.get("request") or {
            "model": config.get("model"),
            "prompt_mode": config.get("prompt_mode"),
            "prompt": config.get("prompt"),
            "event_context": {
                "event_id": candidate.get("event_id"),
                "start_seconds": candidate.get("start_seconds"),
                "end_seconds": candidate.get("end_seconds"),
                "candidate_time_s": candidate.get("candidate_time_s"),
                "object_observations": candidate.get("object_observations") or [],
                "media_asset_ids": asset_ids,
            },
        }
        records.append({
            "event_id": candidate.get("event_id"),
            "input": request,
            "output": vlm.get("raw_output") or vlm,
            "status": vlm.get("status", "pending"),
        })
    return records


def rag_input_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the exact per-candidate JSON payload saved for RAG."""
    return [
        {
            "event_id": candidate.get("event_id"),
            "status": (candidate.get("vlm") or {}).get("status", "pending"),
            "rag_input": candidate.get("rag_input"),
        }
        for candidate in result.get("candidates") or []
    ]


def vlm_failure_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract user-visible failure details for retryable VLM candidates."""
    records = []
    for candidate in result.get("candidates") or []:
        vlm = candidate.get("vlm") or {}
        if vlm.get("status") == "failed":
            records.append({
                "event_id": candidate.get("event_id"),
                "reason_code": vlm.get("reason_code") or "unknown_error",
                "error_message": vlm.get("error_message") or "상세 오류 메시지가 없습니다.",
            })
    return records


def candidate_clip_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract candidate clip identifiers and source-video timing for display."""
    records = []
    for candidate in result.get("candidates") or []:
        evidence = candidate.get("evidence") or {}
        records.append({
            "event_id": candidate.get("event_id"),
            "candidate_time_s": candidate.get("candidate_time_s"),
            "clip_start_seconds": evidence.get("clip_start_seconds"),
            "clip_end_seconds": evidence.get("clip_end_seconds"),
            "clip_asset_id": evidence.get("clip_asset_id"),
            "annotated_clip_asset_id": evidence.get("annotated_clip_asset_id"),
        })
    return records
