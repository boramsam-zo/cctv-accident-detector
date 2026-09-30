"""Portable one-video X3D-S + YOLO11s inference for server integration.

This is the frozen *offline video* decision used in the SO-TAD evaluation.
It is not a frame-by-frame live-CCTV implementation. YOLO detects objects,
not collisions; X3D-S supplies the collision candidate time. The server owns
the video buffer and sends a surrounding clip to the VLM.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .timeline import THRESHOLD, WINDOW_SECONDS, group_alerts, window_starts


FRAME_SIZE = 182
FRAMES_PER_WINDOW = 16
MEAN = (0.45, 0.45, 0.45)
STD = (0.225, 0.225, 0.225)
YOLO_IMAGE_SIZE = 640
YOLO_CONFIDENCE = 0.25
MAX_VIDEO_SECONDS = 120.0  # Bounded-memory demo/API endpoint.


def collision_region(boxes: list[list[float]], width: int, height: int) -> tuple[int, int, int, int]:
    """Return a padded envelope around detected objects, or the full frame."""
    if not boxes:
        return 2, 2, max(2, width - 3), max(2, height - 3)
    padding = max(4, round(min(width, height) * 0.02))
    return (
        max(0, int(min(box[0] for box in boxes)) - padding),
        max(0, int(min(box[1] for box in boxes)) - padding),
        min(width - 1, int(max(box[2] for box in boxes)) + padding),
        min(height - 1, int(max(box[3] for box in boxes)) + padding),
    )


def annotate_collision_frame(bgr_frame: Any, detections: list[dict[str, Any]],
                             score: float | None = None) -> Any:
    """Return a representative frame with a red accident-candidate envelope."""
    import cv2

    frame = bgr_frame.copy()
    height, width = frame.shape[:2]
    boxes = [row["box_xyxy_px"] for row in detections if row.get("box_xyxy_px")]
    x1, y1, x2, y2 = collision_region(boxes, width, height)
    thickness = max(3, round(min(width, height) / 180))
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), thickness)

    label = "ACCIDENT CANDIDATE"
    if score is not None:
        label += f" {score:.2f}"
    font_scale = max(0.55, min(width, height) / 900)
    (text_width, text_height), baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
    label_height = text_height + baseline + 8
    if y1 >= label_height:
        label_top, label_bottom = y1 - label_height, y1
    else:
        label_top = y1
        label_bottom = min(height - 1, y1 + label_height)
    cv2.rectangle(
        frame, (x1, label_top),
        (min(width - 1, x1 + text_width + 10), label_bottom), (0, 0, 255), -1,
    )
    cv2.putText(
        frame, label, (x1 + 5, label_top + text_height + 4),
        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 2, cv2.LINE_AA,
    )
    return frame


class ModelBundle:
    def __init__(self, x3d_checkpoint: Path, yolo_checkpoint: Path,
                 device: str = "cpu", allow_a100: bool = False):
        import torch
        import torch.nn as nn
        from ultralytics import YOLO

        if not x3d_checkpoint.is_file():
            raise FileNotFoundError(f"X3D-S epoch-7 checkpoint missing: {x3d_checkpoint}")
        if not yolo_checkpoint.is_file():
            raise FileNotFoundError(f"YOLO11s 30-epoch checkpoint missing: {yolo_checkpoint}")
        if device not in ("cpu", "cuda"):
            raise ValueError("device must be 'cpu' or 'cuda'")
        if device == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested, but no CUDA GPU is available")
            gpu_name = torch.cuda.get_device_name(0)
            if "A100" in gpu_name.upper() and not allow_a100:
                raise RuntimeError("A100 detected; set allow_a100 explicitly before using paid A100 time")
            print(f"Inference GPU: {gpu_name}", flush=True)
        else:
            print("Inference device: CPU", flush=True)

        # The training/evaluation used torch.hub's X3D-S factory. Set
        # PYTORCHVIDEO_REPO to a local pytorchvideo checkout for offline use.
        local_repo = os.getenv("PYTORCHVIDEO_REPO")
        if local_repo:
            model = torch.hub.load(local_repo, "x3d_s", pretrained=False, source="local")
        else:
            model = torch.hub.load("facebookresearch/pytorchvideo", "x3d_s", pretrained=False)
        features = model.blocks[-1].proj.in_features
        model.blocks[-1].proj = nn.Linear(features, 2)
        model.blocks[-1].activation = None
        checkpoint = torch.load(x3d_checkpoint, map_location="cpu", weights_only=True)
        if checkpoint.get("epoch") != 7:
            raise ValueError(f"Expected current epoch-7 X3D-S, got epoch={checkpoint.get('epoch')}")
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        self.x3d = model.to(device).eval()
        self.yolo = YOLO(str(yolo_checkpoint))
        if self.yolo.task != "detect":
            raise ValueError(f"Expected YOLO object detection checkpoint, got {self.yolo.task}")
        names = self.yolo.names
        self.yolo_names = ({int(k): str(v) for k, v in names.items()}
                           if isinstance(names, dict) else
                           {i: str(v) for i, v in enumerate(names)})
        self.torch = torch
        self.device = device
        self.mean = torch.tensor(MEAN, device=device).view(1, 3, 1, 1, 1)
        self.std = torch.tensor(STD, device=device).view(1, 3, 1, 1, 1)

    def collision_probabilities(self, clips: list[Any]) -> list[float]:
        import numpy as np

        if not clips:
            return []
        x = self.torch.from_numpy(np.stack(clips)).to(self.device)
        x = (x.float().div_(255.0) - self.mean) / self.std
        amp = (self.torch.autocast(device_type="cuda", dtype=self.torch.float16)
               if self.device == "cuda" else nullcontext())
        with self.torch.inference_mode(), amp:
            logits = self.x3d(x)
        return self.torch.softmax(logits.float(), dim=1)[:, 1].cpu().tolist()

    def detect_objects(self, bgr_frame: Any) -> list[dict[str, Any]]:
        height, width = bgr_frame.shape[:2]
        result = self.yolo.predict(
            source=bgr_frame, imgsz=YOLO_IMAGE_SIZE, conf=YOLO_CONFIDENCE,
            device=0 if self.device == "cuda" else "cpu",
            half=self.device == "cuda", verbose=False,
        )[0]
        boxes = result.boxes
        if boxes is None:
            return []
        rows = []
        for detection_index, (xyxy, score, cls) in enumerate(zip(
                boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(),
                boxes.cls.cpu().tolist())):
            class_id = int(cls)
            x1, y1, x2, y2 = (float(value) for value in xyxy)
            rows.append({
                "detection_index": detection_index,
                "class_id": class_id,
                "class_name": self.yolo_names.get(class_id, str(class_id)),
                "confidence": float(score),
                "box_xyxy_px": [x1, y1, x2, y2],
                "box_xyxy_normalized": [x1 / width, y1 / height, x2 / width, y2 / height],
            })
        return rows

    def annotate_video(self, source_path: Path, output_path: Path, *,
                       collision_start_s: float | None = None,
                       collision_end_s: float | None = None,
                       collision_score: float | None = None) -> int:
        """Render YOLO boxes and a red region during the X3D candidate interval."""
        import cv2
        import numpy as np

        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open clip for YOLO annotation: {source_path}")
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            capture.release()
        if not np.isfinite(fps) or fps <= 0 or width <= 0 or height <= 0:
            raise RuntimeError(f"Invalid clip metadata for YOLO annotation: {source_path}")

        writer = cv2.VideoWriter(
            str(output_path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"Cannot create annotated clip: {output_path}")
        frame_count = 0
        try:
            results = self.yolo.predict(
                source=str(source_path), imgsz=YOLO_IMAGE_SIZE, conf=YOLO_CONFIDENCE,
                device=0 if self.device == "cuda" else "cpu",
                half=self.device == "cuda", verbose=False, stream=True,
            )
            for result in results:
                frame = result.plot()
                frame_time = (frame_count + 0.5) / fps
                highlight = (collision_start_s is not None and collision_end_s is not None
                             and collision_start_s <= frame_time <= collision_end_s)
                if highlight:
                    boxes = (result.boxes.xyxy.cpu().tolist()
                             if result.boxes is not None else [])
                    x1, y1, x2, y2 = collision_region(boxes, width, height)
                    thickness = max(3, round(min(width, height) / 180))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), thickness)
                    label = "ACCIDENT CANDIDATE"
                    if collision_score is not None:
                        label += f" {collision_score:.2f}"
                    font_scale = max(0.55, min(width, height) / 900)
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
                    label_height = text_height + baseline + 8
                    if y1 >= label_height:
                        label_top, label_bottom = y1 - label_height, y1
                    else:
                        label_top = y1
                        label_bottom = min(height - 1, y1 + label_height)
                    cv2.rectangle(
                        frame, (x1, label_top),
                        (min(width - 1, x1 + text_width + 10), label_bottom),
                        (0, 0, 255), -1,
                    )
                    cv2.putText(
                        frame, label, (x1 + 5, label_top + text_height + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 2,
                        cv2.LINE_AA,
                    )
                writer.write(frame)
                frame_count += 1
        finally:
            writer.release()
        if frame_count == 0:
            raise RuntimeError(f"YOLO produced no annotated frames: {source_path}")
        return frame_count


def decode_resized_video(path: Path):
    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open MP4: {path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0:
            raise RuntimeError(f"Invalid FPS: {path}")
        frames = []
        max_frames = int(MAX_VIDEO_SECONDS * fps) + 1
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            if len(frames) >= max_frames:
                raise ValueError(f"Video longer than {MAX_VIDEO_SECONDS}s; use a streaming worker")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            frames.append(cv2.resize(rgb, (FRAME_SIZE, FRAME_SIZE), interpolation=cv2.INTER_AREA))
        if len(frames) < 2:
            raise RuntimeError(f"Too few decodable frames: {path}")
        return np.stack(frames), fps
    finally:
        capture.release()


def build_clips(frames, fps: float):
    import numpy as np

    duration = len(frames) / fps
    for start in window_starts(duration):
        sample_times = np.linspace(start, start + WINDOW_SECONDS,
                                   FRAMES_PER_WINDOW, endpoint=False)
        indices = np.clip(np.rint(sample_times * fps).astype(np.int64),
                          0, len(frames) - 1)
        clip = np.ascontiguousarray(frames[indices].transpose(3, 0, 1, 2))
        yield float(start), float(min(start + WINDOW_SECONDS, duration)), clip


def frame_at(video_path: Path, timestamp_s: float):
    """Read one frame for YOLO object context at an X3D candidate time."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot reopen video for YOLO: {video_path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or count < 1:
            raise RuntimeError("Invalid video FPS or frame count")
        frame_index = max(0, min(round(timestamp_s * fps), count - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Cannot read candidate frame {frame_index}")
        return frame
    finally:
        cap.release()


def analyze_video(video_path: Path, output_dir: Path, models: ModelBundle,
                  batch_size: int = 8) -> dict[str, Any]:
    """Analyze one local MP4; return timing for server-owned VLM buffering."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    frames, fps = decode_resized_video(video_path)
    duration = len(frames) / fps
    windows = []
    pending = []
    bounds = []

    def flush():
        if not pending:
            return
        probabilities = models.collision_probabilities(pending)
        if len(probabilities) != len(bounds):
            raise RuntimeError("X3D output count does not match input window count")
        for (start, end), probability in zip(bounds, probabilities):
            windows.append({"start_s": start, "end_s": end,
                            "collision_probability": float(probability),
                            "is_positive": bool(probability >= THRESHOLD)})
        pending.clear()
        bounds.clear()

    for start, end, clip in build_clips(frames, fps):
        pending.append(clip)
        bounds.append((start, end))
        if len(pending) >= batch_size:
            flush()
    flush()
    del frames
    events = group_alerts(windows)
    handoffs = []
    for index, event in enumerate(events):
        event_id = f"event_{index:03d}"
        event["event_id"] = event_id
        event["yolo_objects"] = models.detect_objects(
            frame_at(video_path, event["candidate_time_s"])
        )
        handoff = {
            "schema_version": "1.0",
            "event_id": event_id,
            "video_id": video_path.name,
            "x3d_collision_candidate": True,
            "candidate_time_s": event["candidate_time_s"],
            "available_after_video_time_s": event["available_after_video_time_s"],
            "candidate_window_s": [event["first_window_start_s"],
                                   event["first_window_end_s"]],
            "x3d_probability_at_trigger": event["first_window_probability"],
            "yolo_role": "object_detection_only_not_collision_verdict",
            "yolo_frame_time_s": event["candidate_time_s"],
            "yolo_objects": event["yolo_objects"],
            "yolo_object_count": len(event["yolo_objects"]),
            "server_action": "Cut pre/post-event context from the server video buffer and send it to VLM",
            "note": "Candidate time is the first positive X3D window midpoint, not a verified impact timestamp.",
        }
        handoffs.append(handoff)

    result = {
        "schema_version": "1.0",
        "video_filename": video_path.name,
        "duration_s": duration,
        "fps": fps,
        "device": models.device,
        "x3d": {
            "model": "x3d_s_real_so_tad_v1_epoch7",
            "label_mapping": {"0": "Normal", "1": "Collision"},
            "threshold": THRESHOLD,
            "window_seconds": WINDOW_SECONDS,
            "stride_seconds": 1.0,
            "decision": "Collision" if events else "Normal",
            "max_collision_probability": max(w["collision_probability"] for w in windows),
            "windows": windows,
        },
        "events": events,
        "vlm_handoffs": handoffs,
        "processing_seconds": time.perf_counter() - started,
        "warning": "Candidate times are not verified crash times; server/VLM manages the video buffer.",
    }
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "vlm_handoffs.json").write_text(
        json.dumps(handoffs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
