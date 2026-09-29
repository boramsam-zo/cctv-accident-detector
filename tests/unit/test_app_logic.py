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
    """Streamlit 앱 파일을 화면 실행 없이 테스트 모듈로 불러온다."""
    spec = importlib.util.spec_from_file_location("streamlit_demo_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load_app_module()


class SessionState(dict):
    """Attribute-style dict standing in for st.session_state."""

    def __getattr__(self, name):
        """세션 값을 Streamlit과 같이 속성으로 조회한다."""
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        """속성 할당을 세션 딕셔너리 값으로 저장한다."""
        self[name] = value


def fake_streamlit(state: SessionState) -> SimpleNamespace:
    """지정한 세션 상태만 가진 Streamlit 대역을 만든다."""
    return SimpleNamespace(session_state=state)


def result(status: str, outcome: str) -> dict:
    """상태 문구 테스트용 최소 분석 결과를 만든다."""
    return {"status": status, "detection_outcome": outcome}


class StatusMessageTest(unittest.TestCase):
    def test_completed_without_candidates_is_success_with_no_candidate_text(self) -> None:
        """후보 없는 완료 상태를 성공으로 표시하고 후보 없음 문구를 보여준다."""
        level, text = app.status_message(result("completed", "no_candidates"))
        self.assertEqual("success", level)
        self.assertIn("후보가 없습니다", text)

    def test_completed_with_candidates_asks_for_review(self) -> None:
        """후보가 있는 완료 상태에서 검토 안내 문구를 보여준다."""
        level, text = app.status_message(result("completed", "candidates_found"))
        self.assertEqual("success", level)
        self.assertIn("검토", text)

    def test_partial_is_warning_regardless_of_outcome(self) -> None:
        """부분 완료는 탐지 결과와 관계없이 경고로 표시한다."""
        for outcome in ("unknown", "candidates_found"):
            with self.subTest(outcome=outcome):
                level, _ = app.status_message(result("partial", outcome))
                self.assertEqual("warning", level)

    def test_failed_is_error(self) -> None:
        """실패 상태에 오류 수준과 재시도 안내를 표시한다."""
        level, text = app.status_message(result("failed", "unknown"))
        self.assertEqual("error", level)
        self.assertIn("재시도", text)

    def test_enriching_is_info(self) -> None:
        """후처리 중에는 보고서 생성 안내를 정보 수준으로 표시한다."""
        level, text = app.status_message(result("enriching", "candidates_found"))
        self.assertEqual("info", level)
        self.assertIn("보고서", text)

    def test_in_progress_statuses_are_info(self) -> None:
        """대기·배정·실행 중 상태를 분석 진행 정보로 표시한다."""
        for status in ("queued", "dispatching", "running"):
            with self.subTest(status=status):
                level, text = app.status_message(result(status, "pending"))
                self.assertEqual("info", level)
                self.assertIn("분석 중", text)

    def test_every_contract_status_has_a_label(self) -> None:
        """계약에 정의된 모든 작업 상태에 화면 라벨이 있는지 확인한다."""
        contract_statuses = {"queued", "dispatching", "running", "enriching", "completed", "partial", "failed"}
        self.assertEqual(contract_statuses, set(app.STATUS_LABELS))


class InitializeStateTest(unittest.TestCase):
    CASES = [{"job_id": "job-a"}, {"job_id": "job-b"}]

    def test_sets_defaults_on_empty_session(self) -> None:
        """빈 세션에 화면·업로드·검토 상태의 기본값을 채운다."""
        state = SessionState()
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)

        self.assertEqual([], state.uploaded_videos)
        self.assertEqual("intake", state.current_page)
        self.assertFalse(state.analysis_requested)
        self.assertEqual({}, state.review_by_event)

    def test_falls_back_to_first_case_when_default_job_is_missing(self) -> None:
        """기본 작업 ID가 없으면 첫 데모 작업을 선택한다."""
        state = SessionState()
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)
        self.assertEqual("job-a", state.selected_job_id)

    def test_keeps_existing_values(self) -> None:
        """세션 초기화가 이미 선택된 화면과 작업을 덮어쓰지 않는다."""
        state = SessionState(current_page="analysis", selected_job_id="job-b")
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.initialize_state(self.CASES)
        self.assertEqual("analysis", state.current_page)
        self.assertEqual("job-b", state.selected_job_id)


class OpenAnalysisTest(unittest.TestCase):
    def test_queues_only_the_opened_video_and_switches_page(self) -> None:
        """선택한 영상만 대기 상태로 바꾸고 분석 화면으로 이동한다."""
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
        """화면 이동 함수가 현재 페이지를 요청한 값으로 바꾼다."""
        state = SessionState(current_page="intake")
        with mock.patch.object(app, "st", fake_streamlit(state)):
            app.navigate_to("analysis")
        self.assertEqual("analysis", state.current_page)


if __name__ == "__main__":
    unittest.main()
