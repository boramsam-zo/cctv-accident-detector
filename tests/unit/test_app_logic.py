"""Unit tests for the Streamlit demo app's state and status logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "apps" / "streamlit" / "app.py"


def load_app_module():
    spec = importlib.util.spec_from_file_location("streamlit_demo_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load_app_module()


class SessionState(dict):
    """Attribute-style dict standing in for st.session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


def fake_streamlit(state: SessionState) -> SimpleNamespace:
    return SimpleNamespace(session_state=state)


def result(status: str, outcome: str) -> dict:
    return {"status": status, "detection_outcome": outcome}


class StatusMessageTest(unittest.TestCase):
    def test_completed_without_candidates_is_success_with_no_candidate_text(self) -> None:
        level, text = app.status_message(result("completed", "no_candidates"))
        self.assertEqual("success", level)
        self.assertIn("후보가 없습니다", text)

    def test_completed_with_candidates_asks_for_review(self) -> None:
        level, text = app.status_message(result("completed", "candidates_found"))
        self.assertEqual("success", level)
        self.assertIn("검토", text)

    def test_partial_is_warning_regardless_of_outcome(self) -> None:
        for outcome in ("unknown", "candidates_found"):
            with self.subTest(outcome=outcome):
                level, _ = app.status_message(result("partial", outcome))
                self.assertEqual("warning", level)

    def test_failed_is_error(self) -> None:
        level, text = app.status_message(result("failed", "unknown"))
        self.assertEqual("error", level)
        self.assertIn("재시도", text)

    def test_enriching_is_info(self) -> None:
        level, text = app.status_message(result("enriching", "candidates_found"))
        self.assertEqual("info", level)
        self.assertIn("보고서", text)

    def test_in_progress_statuses_are_info(self) -> None:
        for status in ("queued", "dispatching", "running"):
            with self.subTest(status=status):
                level, text = app.status_message(result(status, "pending"))
                self.assertEqual("info", level)
                self.assertIn("분석 중", text)

    def test_every_contract_status_has_a_label(self) -> None:
        contract_statuses = {"queued", "dispatching", "running", "enriching", "completed", "partial", "failed"}
        self.assertEqual(contract_statuses, set(app.STATUS_LABELS))


class InitializeStateTest(unittest.TestCase):
    CASES = [{"job_id": "job-a"}, {"job_id": "job-b"}]

    def test_sets_defaults_on_empty_session(self) -> None:
        state = SessionState()
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)

        self.assertEqual([], state.uploaded_videos)
        self.assertEqual("intake", state.current_page)
        self.assertFalse(state.analysis_requested)
        self.assertEqual({}, state.review_by_event)

    def test_falls_back_to_first_case_when_default_job_is_missing(self) -> None:
        state = SessionState()
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)
        self.assertEqual("job-a", state.selected_job_id)

    def test_keeps_existing_values(self) -> None:
        state = SessionState(current_page="analysis", selected_job_id="job-b")
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)
        self.assertEqual("analysis", state.current_page)
        self.assertEqual("job-b", state.selected_job_id)


class OpenAnalysisTest(unittest.TestCase):
    def test_queues_only_the_opened_video_and_switches_page(self) -> None:
        state = SessionState(
            current_page="intake",
            selected_upload_index=0,
            analysis_requested=False,
            uploaded_videos=[
                {"name": "a.mp4", "status": "ready"},
                {"name": "b.mp4", "status": "ready"},
                {"name": "c.mp4", "status": "completed"},
            ],
        )
        original_videos = state.uploaded_videos
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.open_analysis(1)

        self.assertEqual("analysis", state.current_page)
        self.assertEqual(1, state.selected_upload_index)
        self.assertTrue(state.analysis_requested)
        self.assertEqual(["ready", "queued", "completed"], [video["status"] for video in state.uploaded_videos])
        # The previous list is replaced, not mutated in place.
        self.assertEqual("ready", original_videos[1]["status"])


class NavigateToTest(unittest.TestCase):
    def test_sets_current_page(self) -> None:
        state = SessionState(current_page="intake")
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.navigate_to("analysis")
        self.assertEqual("analysis", state.current_page)


if __name__ == "__main__":
    unittest.main()
