"""Checks that the demo analysis cases follow the rules in docs/contracts/service_contract.md."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_CASES_PATH = PROJECT_ROOT / "docs" / "contracts" / "demo-analysis-cases-v0.2.json"

JOB_STATUSES = {"queued", "dispatching", "running", "enriching", "completed", "partial", "failed"}
DETECTION_OUTCOMES = {"pending", "candidates_found", "no_candidates", "unknown"}
STAGES = {"accident", "objects", "evidence", "vlm", "rag", "report"}
STAGE_STATUSES = {"pending", "running", "completed", "skipped", "failed", "insufficient_evidence"}


def load_cases() -> list[dict]:
    """계약 검증에 사용할 데모 분석 사례 JSON을 읽는다."""
    with DEMO_CASES_PATH.open(encoding="utf-8-sig") as file:
        return json.load(file)["cases"]


class DemoCasesContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """모든 데모 계약 테스트가 공유할 사례를 한 번 읽는다."""
        cls.cases = load_cases()

    def test_job_ids_are_unique(self) -> None:
        """데모 분석 사례마다 작업 ID가 중복되지 않는지 확인한다."""
        job_ids = [case["job_id"] for case in self.cases]
        self.assertEqual(len(job_ids), len(set(job_ids)))

    def test_status_and_outcome_use_contract_enums(self) -> None:
        """작업 상태와 탐지 결과가 계약의 허용값 안에 있는지 확인한다."""
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertIn(case["status"], JOB_STATUSES)
                self.assertIn(case["detection_outcome"], DETECTION_OUTCOMES)

    def test_every_case_is_marked_demo(self) -> None:
        """모든 샘플 결과가 실제 작업과 구분되도록 데모로 표시됐는지 확인한다."""
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertIs(True, case["is_demo"])

    def test_coverage_windows_add_up(self) -> None:
        """예정된 창 수가 예측·미분류·대기 창 수의 합과 일치하는지 확인한다."""
        # scheduled_windows = predicted_windows + unclassified_windows + pending_windows
        for case in self.cases:
            coverage = case["coverage"]
            with self.subTest(job_id=case["job_id"]):
                self.assertEqual(
                    coverage["scheduled_windows"],
                    coverage["predicted_windows"] + coverage["unclassified_windows"] + coverage["pending_windows"],
                )
                self.assertLessEqual(coverage["requested_start_seconds"], coverage["requested_end_seconds"])

    def test_no_candidates_requires_full_coverage_and_zero_candidates(self) -> None:
        """후보 없음 결과에 미처리 구간이나 후보 목록이 없는지 확인한다."""
        for case in self.cases:
            if case["detection_outcome"] != "no_candidates":
                continue
            coverage = case["coverage"]
            with self.subTest(job_id=case["job_id"]):
                self.assertEqual([], case["candidates"])
                self.assertGreater(coverage["scheduled_windows"], 0)
                self.assertEqual(0, coverage["unclassified_windows"])
                self.assertEqual(0, coverage["pending_windows"])

    def test_candidates_found_matches_candidate_list(self) -> None:
        """후보 발견 결과가 실제 후보 목록의 존재 여부와 일치하는지 확인한다."""
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                has_candidates = bool(case["candidates"])
                self.assertEqual(case["detection_outcome"] == "candidates_found", has_candidates)

    def test_stages_are_complete_and_valid(self) -> None:
        """모든 처리 단계가 있고 각 단계 상태가 허용값인지 확인한다."""
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertEqual(STAGES, set(case["stages"]))
                for stage in case["stages"].values():
                    self.assertIn(stage["status"], STAGE_STATUSES)

    def test_candidate_time_ranges_and_scores_are_sane(self) -> None:
        """후보 시간·점수·근거 구간·보고서 이벤트 ID의 일관성을 확인한다."""
        for case in self.cases:
            for candidate in case["candidates"]:
                with self.subTest(job_id=case["job_id"], event_id=candidate["event_id"]):
                    self.assertLess(candidate["start_seconds"], candidate["end_seconds"])
                    self.assertGreaterEqual(candidate["score"], 0.0)
                    self.assertLessEqual(candidate["score"], 1.0)
                    evidence = candidate["evidence"]
                    self.assertLessEqual(evidence["clip_start_seconds"], candidate["start_seconds"])
                    self.assertGreaterEqual(evidence["clip_end_seconds"], candidate["end_seconds"])
                    self.assertEqual(candidate["event_id"], candidate["report"]["source_event_id"])

    def test_failed_jobs_report_an_error(self) -> None:
        """실패한 작업에 재시도 가능 여부가 포함된 오류가 있는지 확인한다."""
        for case in self.cases:
            if case["status"] != "failed":
                continue
            with self.subTest(job_id=case["job_id"]):
                self.assertTrue(case["errors"])
                for error in case["errors"]:
                    self.assertIsInstance(error["retryable"], bool)


if __name__ == "__main__":
    unittest.main()
