"""Upload one MP4 and verify the Modal → Gemini JSON path through the public API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from apps.streamlit.backend_client import BackendClient, BackendError
from services.backend.gemini_vlm import RagInput
from services.backend.scene_facts import SceneFacts, validate_provenance


TERMINAL_STATUSES = {"completed", "partial", "failed"}


def main() -> int:
    """Submit a sample video, poll its job, and print validated Gemini JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Local MP4 to upload through FastAPI")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()
    if not args.video.is_file() or args.video.suffix.lower() != ".mp4":
        parser.error("video must be an existing MP4 file")
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("timeout and poll interval must be positive")
    client = BackendClient.from_env()
    if client is None:
        parser.error("BACKEND_API_URL and APP_API_KEY are required in the shell environment")

    try:
        health = client.health()
        if health.get("status") != "ok":
            raise ValueError(f"Unexpected backend health response: {health}")
        profile_id = client.analysis_profile()
        video = client.upload_video(args.video.name, args.video.read_bytes(), None,
                                    f"smoke-upload-{uuid4().hex}")
        job = client.create_job(video["source_video_id"], profile_id,
                                f"smoke-job-{uuid4().hex}")
        job_id = job["job_id"]
        print(f"uploaded video_id={video['source_video_id']} job_id={job_id}", flush=True)
        deadline = time.monotonic() + args.timeout_seconds
        last_status = None
        while True:
            result = client.get_job(job_id)
            status = result["status"]
            if status != last_status:
                print(f"job status={status} stages={json.dumps(result.get('stages'), ensure_ascii=False)}",
                      flush=True)
                last_status = status
            if status in TERMINAL_STATUSES:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Job {job_id} did not finish within {args.timeout_seconds}s")
            time.sleep(args.poll_seconds)

        candidates = result.get("candidates") or []
        rag_inputs = []
        for candidate in candidates:
            payload = candidate.get("rag_input")
            if not payload:
                continue
            if payload.get("schema_version") == "scene-facts-v2":
                vlm = candidate["vlm"]
                facts = SceneFacts.model_validate(vlm["raw_output"])
                validate_provenance(facts, vlm["request"]["input"])
                rag_inputs.append(payload)
            else:
                rag_inputs.append(RagInput.model_validate(payload).model_dump(mode="json"))
        print(json.dumps({"job_id": job_id, "status": status,
                          "detection_outcome": result.get("detection_outcome"),
                          "candidate_count": len(candidates), "gemini_json": rag_inputs,
                          "errors": result.get("errors") or []},
                         ensure_ascii=False, indent=2))
        if status != "completed" or not rag_inputs or len(rag_inputs) != len(candidates):
            print("Modal → Gemini JSON verification is incomplete; inspect worker logs.", file=sys.stderr)
            return 1
        return 0
    except (BackendError, ValueError, TimeoutError) as exc:
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
