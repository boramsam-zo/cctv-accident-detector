from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.streamlit import e2e_test


def test_start_analysis_uses_uploaded_source_video_id():
    client = Mock()
    client.upload_video.return_value = {"source_video_id": "video-1"}
    client.create_job.return_value = {"job_id": "job-1"}
    uploaded = SimpleNamespace(name="sample.mp4", getvalue=lambda: b"video")
    state = SimpleNamespace()

    with patch.object(e2e_test.st, "session_state", state):
        e2e_test.start_analysis(
            client, uploaded, "profile-1", "gemini-test", "prompt", "replace")

    client.create_job.assert_called_once_with(
        "video-1", "profile-1", client.create_job.call_args.args[2],
        vlm_model="gemini-test", vlm_prompt="prompt", vlm_prompt_mode="replace",
        defer_vlm=False)
    assert state.e2e_job_id == "job-1"


def test_manual_mode_preserves_candidate_review_before_gemini():
    client = Mock()
    client.upload_video.return_value = {"source_video_id": "video-1"}
    client.create_job.return_value = {"job_id": "job-1"}
    uploaded = SimpleNamespace(name="sample.mp4", getvalue=lambda: b"video")
    with patch.object(e2e_test.st, "session_state", SimpleNamespace()):
        e2e_test.start_analysis(client, uploaded, "profile", "model", "", "prepend", manual_vlm=True)
    assert client.create_job.call_args.kwargs["defer_vlm"] is True


def test_freeze_elapsed_time_stops_once_analysis_finishes():
    assert e2e_test.freeze_elapsed_time("running", None, 12.0) is None
    assert e2e_test.freeze_elapsed_time("completed", None, 15.5) == 15.5
    assert e2e_test.freeze_elapsed_time("completed", 15.5, 99.0) == 15.5


def test_elapsed_seconds_uses_frozen_completion_time():
    state = SimpleNamespace(e2e_started_at=10.0, e2e_finished_at=15.5)

    with patch.object(e2e_test.st, "session_state", state), \
            patch.object(e2e_test.time, "monotonic", return_value=99.0):
        assert e2e_test.elapsed_seconds() == 5.5


def test_scene_facts_io_renders_and_exports_job_json(scene_payload):
    from streamlit.testing.v1 import AppTest
    result = {"candidates": [{"event_id": "ev", "vlm": {"status": "completed",
              "raw_output": scene_payload(), "request": {"input": {"schema_version": "vlm-input-v2"}}}}]}
    app = AppTest.from_string("from apps.streamlit.e2e_test import render_vlm_io\nrender_vlm_io(" + repr(result) + ")").run(timeout=20)
    assert not app.exception
    assert len(app.json) == 2
    assert len(app.get("download_button")) == 1
    assert any("정확도" in caption.value for caption in app.caption)
