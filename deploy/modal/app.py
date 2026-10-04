"""Modal GPU inference entrypoint for the shared accident_vision package."""

import modal


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libgl1")
    .pip_install("torch", "torchvision", "numpy<2", "opencv-python-headless",
                 "ultralytics", "pytorchvideo", "fvcore", "iopath", "av",
                 "parameterized", "networkx", "boto3")
    .env({"PYTHONPATH": "/root"})
    .add_local_dir("src/accident_vision", remote_path="/root/accident_vision")
)
app = modal.App("cctv-accident-inference")


@app.function(image=image, gpu="L4", timeout=900, retries=0, max_containers=2,
              secrets=[modal.Secret.from_name("cctv-s3")])
def analyze_video_job(assignment: dict) -> dict:
    """Run X3D-S and YOLO11s, then persist evidence and manifests in S3."""
    import hashlib
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    import boto3
    import cv2

    from accident_vision.pipeline import (
        ModelBundle, analyze_video, annotate_collision_frame, frame_at,
    )

    if assignment.get("schema_version") != "modal-inference-v1":
        raise ValueError("unsupported_assignment_schema")
    source = assignment["input_object"]
    bucket, source_key = source["bucket"], source["key"]
    prefix = assignment["output_prefix"]
    run_id = assignment["run_id"]
    if not prefix.endswith(f"jobs/{assignment['job_id']}/runs/{run_id}/attempt-{assignment['attempt']}/"):
        raise ValueError("invalid_output_prefix")
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))

    def upload(key: str, blob: bytes, mime: str) -> dict:
        """Write evidence to the assigned S3 prefix and return its digest."""
        if not key.startswith(prefix):
            raise ValueError("invalid_output_key")
        s3.put_object(Bucket=bucket, Key=key, Body=blob, ContentType=mime)
        return {"key": key, "sha256": hashlib.sha256(blob).hexdigest(), "mime_type": mime}

    def upload_json(key: str, value: dict) -> dict:
        """Store a UTF-8 manifest and return its S3 key and SHA256."""
        ref = upload(key, json.dumps(value, ensure_ascii=False).encode(), "application/json")
        return {"manifest_key": ref["key"], "manifest_sha256": ref["sha256"]}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        video_path = root / "original.mp4"
        s3.download_file(bucket, source_key, str(video_path))
        if hashlib.sha256(video_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("source_sha256_mismatch")
        assigned_weights = assignment.get("model_weights")
        if assigned_weights:
            weight_refs = assigned_weights
        else:
            weights_bucket = os.environ["MODEL_WEIGHTS_S3_BUCKET"]
            weight_refs = {
                "x3d": {"bucket": weights_bucket, "key": os.environ["X3D_WEIGHTS_S3_KEY"],
                        "sha256": os.environ["X3D_WEIGHTS_SHA256"]},
                "yolo": {"bucket": weights_bucket, "key": os.environ["YOLO_WEIGHTS_S3_KEY"],
                         "sha256": os.environ["YOLO_WEIGHTS_SHA256"]},
            }
        weights = {}
        for name in ("x3d", "yolo"):
            ref = weight_refs[name]
            weight_bucket, key = ref["bucket"], ref["key"]
            if not weight_bucket or not key or "://" in key or key.startswith("/") or ".." in key.split("/"):
                raise ValueError(f"invalid_{name}_weights_reference")
            path = root / f"{name}.pt"
            s3.download_file(weight_bucket, key, str(path))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_digest = ref["sha256"]
            if digest != expected_digest:
                raise ValueError(f"{name}_weights_sha256_mismatch")
            weights[name] = {"path": path, "sha256": digest}
        models = ModelBundle(weights["x3d"]["path"], weights["yolo"]["path"], device="cuda")
        analysis = analyze_video(video_path, root / "analysis", models)
        duration = min(float(analysis["duration_s"]), float(assignment["duration_seconds"]))
        event_refs = []
        for sequence, event in enumerate(analysis["events"], start=1):
            event_id = f"{run_id}-{sequence:03d}"
            candidate_time = float(event["candidate_time_s"])
            clip_start = max(0.0, candidate_time - 2.0)
            clip_end = min(duration, candidate_time + 2.0)
            clip_path = root / f"{event_id}.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", str(clip_start), "-i", str(video_path),
                            "-t", str(clip_end - clip_start), "-an", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(clip_path)], check=True)
            clip = upload(f"{prefix}events/{event_id}/clip.mp4",
                          clip_path.read_bytes(), "video/mp4")
            annotated_avi_path = root / f"{event_id}-annotated.avi"
            annotated_clip_path = root / f"{event_id}-annotated.mp4"
            models.annotate_video(
                clip_path,
                annotated_avi_path,
                collision_start_s=max(0.0, float(event["start_s"]) - clip_start),
                collision_end_s=min(clip_end - clip_start,
                                    float(event["end_s"]) - clip_start),
                collision_score=float(event["peak_probability"]),
            )
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(annotated_avi_path), "-an", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            str(annotated_clip_path)], check=True)
            annotated_clip = upload(f"{prefix}events/{event_id}/annotated.mp4",
                                    annotated_clip_path.read_bytes(), "video/mp4")
            representative_frame = annotate_collision_frame(
                frame_at(video_path, candidate_time),
                event["yolo_objects"],
                float(event["peak_probability"]),
            )
            ok, image_data = cv2.imencode(".jpg", representative_frame)
            if not ok:
                raise ValueError("candidate_frame_encode_failed")
            frame = upload(f"{prefix}events/{event_id}/frame.jpg",
                           image_data.tobytes(), "image/jpeg")
            frame["source_time_seconds"] = candidate_time
            manifest = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                        "event_id": event_id, "sequence_number": sequence,
                        "start_seconds": max(0.0, float(event["start_s"])),
                        "end_seconds": min(duration, float(event["end_s"])),
                        "candidate_time_s": candidate_time,
                        "score": float(event["peak_probability"]),
                        "score_type": "max_window_score",
                        "prediction_ids": [],
                        "object_observations": event["yolo_objects"],
                        "evidence": {"clip_start_seconds": clip_start,
                                     "clip_end_seconds": clip_end, "clip": clip,
                                     "annotated_clip": annotated_clip,
                                     "frames": [frame]}}
            event_refs.append(upload_json(f"{prefix}events/{event_id}/manifest.json", manifest))
        window_count = len(analysis["x3d"]["windows"])
        families = assignment.get("model_families") or {}
        final = {"schema_version": "service-draft-v0.2", "run_id": run_id,
                 "coverage": {"requested_start_seconds": 0.0,
                              "requested_end_seconds": duration,
                              "scheduled_windows": window_count,
                              "predicted_windows": window_count,
                              "unclassified_windows": 0, "pending_windows": 0,
                              "unknown_ranges": []},
                 "models": {"objects": {"family": families.get("yolo", "YOLO11s"),
                                        "weights_sha256": weights["yolo"]["sha256"]},
                            "accident": {"family": families.get("x3d", "X3D-S"),
                                         "weights_sha256": weights["x3d"]["sha256"]}},
                 "errors": []}
        final_ref = upload_json(f"{prefix}final.json", final)
        return {"schema_version": "modal-inference-v1", "run_id": run_id,
                "events": event_refs,
                "final_manifest_key": final_ref["manifest_key"],
                "final_manifest_sha256": final_ref["manifest_sha256"]}
