"""Pure timing and event grouping shared by CLI and server inference."""

from __future__ import annotations

import math
from typing import Any


WINDOW_SECONDS = 2.0
STRIDE_SECONDS = 1.0
THRESHOLD = 0.5


def window_starts(duration: float) -> list[float]:
    """Match the frozen SO-TAD 400-video evaluation's window placement."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be positive and finite")
    if duration <= WINDOW_SECONDS:
        return [0.0]
    count = int(math.floor((duration - WINDOW_SECONDS + 1e-6) / STRIDE_SECONDS))
    starts = [i * STRIDE_SECONDS for i in range(count + 1)]
    last = duration - WINDOW_SECONDS
    if last - starts[-1] > 1e-6:
        starts.append(last)
    return starts


def group_alerts(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive positive windows; a negative window breaks the event."""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in windows:
        if row["collision_probability"] < THRESHOLD:
            current = None
            continue
        if current is None:
            current = {
                "start_s": row["start_s"],
                "end_s": row["end_s"],
                "positive_windows": 0,
                "first_window_start_s": row["start_s"],
                "first_window_end_s": row["end_s"],
                "first_window_probability": row["collision_probability"],
                "candidate_time_s": (row["start_s"] + row["end_s"]) / 2,
                "available_after_video_time_s": row["end_s"],
                "peak_probability": -1.0,
                "peak_window_start_s": None,
                "peak_window_end_s": None,
            }
            events.append(current)
        current["end_s"] = row["end_s"]
        current["positive_windows"] += 1
        if row["collision_probability"] > current["peak_probability"]:
            current["peak_probability"] = row["collision_probability"]
            current["peak_window_start_s"] = row["start_s"]
            current["peak_window_end_s"] = row["end_s"]
    return events
