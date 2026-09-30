from apps.streamlit.e2e_metrics import (
    candidate_clip_records,
    rag_input_records,
    summarize_result,
    vlm_failure_records,
    vlm_io_records,
)


def test_summarize_result_counts_modal_and_vlm_outputs():
    result = {
        "status": "completed",
        "coverage": {
            "scheduled_windows": 12,
            "predicted_windows": 11,
            "unclassified_windows": 1,
            "pending_windows": 0,
        },
        "candidates": [
            {
                "score": 0.91,
                "vlm": {
                    "status": "completed",
                    "observations": [{"text": "a"}, {"text": "b"}],
                    "uncertainties": ["dark"],
                },
                "rag_input": {"description": "rear collision"},
            },
            {"score": 0.75, "vlm": {"status": "failed"}},
        ],
        "errors": [{"code": "WINDOW_FAILED"}],
    }

    metrics = summarize_result(result)

    assert metrics == {
        "status_code": 4,
        "scheduled_windows": 12,
        "predicted_windows": 11,
        "unclassified_windows": 1,
        "pending_windows": 0,
        "candidate_count": 2,
        "max_candidate_score": 0.91,
        "vlm_completed_count": 1,
        "vlm_observation_count": 2,
        "vlm_uncertainty_count": 1,
        "rag_input_count": 1,
        "error_count": 1,
    }


def test_vlm_io_records_prefers_exact_saved_request_and_raw_output():
    result = {"execution_config": {"vlm": {"model": "fallback", "prompt": "configured"}},
              "candidates": [{"event_id": "event-1", "evidence": {"frames": []},
                              "vlm": {"status": "completed",
                                      "request": {"model": "gemini-x", "prompt": "final prompt",
                                                  "media_asset_ids": ["frame-1"]},
                                      "raw_output": {"description": "충돌 장면"}}}]}

    records = vlm_io_records(result)

    assert records[0]["input"]["prompt"] == "final prompt"
    assert records[0]["output"] == {"description": "충돌 장면"}


def test_candidate_clip_records_keeps_asset_and_source_timing():
    result = {"candidates": [{"event_id": "event-1", "candidate_time_s": 14.6,
                              "evidence": {"clip_asset_id": "clip-1",
                                           "annotated_clip_asset_id": "boxed-clip-1",
                                           "clip_start_seconds": 12.6,
                                           "clip_end_seconds": 16.6}}]}

    assert candidate_clip_records(result) == [{
        "event_id": "event-1",
        "candidate_time_s": 14.6,
        "clip_start_seconds": 12.6,
        "clip_end_seconds": 16.6,
        "clip_asset_id": "clip-1",
        "annotated_clip_asset_id": "boxed-clip-1",
    }]


def test_rag_input_records_returns_exact_saved_payload_with_event_id():
    rag_input = {
        "event_id": "event-1",
        "candidate_time_s": 14.6,
        "description": "트럭이 전도되었습니다.",
    }
    result = {
        "candidates": [
            {
                "event_id": "event-1",
                "vlm": {"status": "completed"},
                "rag_input": rag_input,
            },
            {
                "event_id": "event-2",
                "vlm": {"status": "pending"},
            },
        ]
    }

    assert rag_input_records(result) == [
        {"event_id": "event-1", "status": "completed", "rag_input": rag_input},
        {"event_id": "event-2", "status": "pending", "rag_input": None},
    ]


def test_vlm_failure_records_exposes_reason_and_safe_fallback():
    result = {"candidates": [
        {"event_id": "event-1", "vlm": {
            "status": "failed", "reason_code": "ClientError",
            "error_message": "quota exceeded",
        }},
        {"event_id": "event-2", "vlm": {
            "status": "failed", "reason_code": "ValueError",
        }},
        {"event_id": "event-3", "vlm": {"status": "completed"}},
    ]}

    assert vlm_failure_records(result) == [
        {"event_id": "event-1", "reason_code": "ClientError",
         "error_message": "quota exceeded"},
        {"event_id": "event-2", "reason_code": "ValueError",
         "error_message": "상세 오류 메시지가 없습니다."},
    ]
