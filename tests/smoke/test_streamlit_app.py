from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "apps" / "streamlit" / "app.py"

DEMO_JOB_IDS = (
    "demo-job-queued",
    "demo-job-running",
    "demo-job-empty",
    "demo-job-partial",
    "demo-job-enriching",
    "demo-job-no-docs",
    "demo-job-vlm-failed",
    "demo-job-failed",
)


class StreamlitAppSmokeTest(unittest.TestCase):
    def test_all_demo_states_render_without_exception(self) -> None:
        """모든 데모 작업 상태가 Streamlit 화면에서 예외 없이 렌더링되는지 확인한다."""
        app = AppTest.from_file(str(APP_PATH))
        app.session_state["current_page"] = "analysis"
        app.run(timeout=20)
        self.assertEqual([], list(app.exception))

        for index, job_id in enumerate(DEMO_JOB_IDS):
            with self.subTest(job_id=job_id):
                job_selector = next(box for box in app.selectbox if box.key == "selected_job_id")
                job_selector.select_index(index).run(timeout=20)
                self.assertEqual([], list(app.exception))

    def test_five_uploaded_video_cards_render(self) -> None:
        """업로드된 영상 다섯 개가 각각 카드로 렌더링되는지 확인한다."""
        app = AppTest.from_file(str(APP_PATH))
        app.session_state["current_page"] = "intake"
        app.session_state["uploaded_videos"] = [
            {
                "name": f"camera-{index}.mp4",
                "content": b"demo-video-bytes",
                "size_bytes": 1024 * index,
                "camera_id": None,
                "status": "ready",
                "request_key": f"demo-key-{index}",
            }
            for index in range(1, 6)
        ]
        app.run(timeout=20)

        self.assertEqual([], list(app.exception))
        card_buttons = [button for button in app.button if str(button.key).startswith("open-card-")]
        self.assertEqual(5, len(card_buttons))


if __name__ == "__main__":
    unittest.main()
