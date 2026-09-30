"""Shared analysis result state used by Modal-backed jobs."""

from .models import Video


def initial_result(video: Video, execution_config: dict | None = None) -> dict:
    """Create the public result skeleton for a newly queued analysis run."""
    return {
        "video": {"duration_seconds": video.duration_seconds, "camera_id": video.camera_id,
                  "recorded_at": video.recorded_at.isoformat() if video.recorded_at else None,
                  "original_asset_id": f"source-{video.id}"},
        "coverage": {"requested_start_seconds": 0.0,
                     "requested_end_seconds": video.duration_seconds,
                     "scheduled_windows": 0, "predicted_windows": 0,
                     "unclassified_windows": 0, "pending_windows": 0,
                     "unknown_ranges": []},
        "models": None,
        "execution_config": execution_config or {},
        "stages": {name: {"status": "pending", "reason_code": None}
                   for name in ("objects", "accident", "evidence", "vlm", "rag", "report")},
        "candidates": [],
        "errors": [],
    }
