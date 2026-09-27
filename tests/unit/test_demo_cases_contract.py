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
    with DEMO_CASES_PATH.open(encoding="utf-8-sig") as file:
        return json.load(file)["cases"]


class DemoCasesContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()

    def test_job_ids_are_unique(self) -> None:
        job_ids = [case["job_id"] for case in self.cases]
        self.assertEqual(len(job_ids), len(set(job_ids)))

    def test_status_and_outcome_use_contract_enums(self) -> None:
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertIn(case["status"], JOB_STATUSES)
                self.assertIn(case["detection_outcome"], DETECTION_OUTCOMES)

    def test_every_case_is_marked_demo(self) -> None:
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertIs(True, case["is_demo"])

    def test_coverage_windows_add_up(self) -> None:
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
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                has_candidates = bool(case["candidates"])
                self.assertEqual(case["detection_outcome"] == "candidates_found", has_candidates)

    def test_stages_are_complete_and_valid(self) -> None:
        for case in self.cases:
            with self.subTest(job_id=case["job_id"]):
                self.assertEqual(STAGES, set(case["stages"]))
                for stage in case["stages"].values():
                    self.assertIn(stage["status"], STAGE_STATUSES)

    def test_candidate_time_ranges_and_scores_are_sane(self) -> None:
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
        for case in self.cases:
            if case["status"] != "failed":
                continue
            with self.subTest(job_id=case["job_id"]):
                self.assertTrue(case["errors"])
                for error in case["errors"]:
                    self.assertIsInstance(error["retryable"], bool)


if __name__ == "__main__":
    unittest.main()
