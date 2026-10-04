import pytest

from scripts.evaluate_vlm_facts import evaluate
from services.backend.scene_facts import SceneFacts, media_context, to_rag_input
from services.backend.rag import build_retrieval_query


def job(payload):
    event = {"event_id": "ev", "evidence": {}}
    return {"candidates": [{"event_id": "ev", "vlm": {"raw_output": payload,
        "request": {"input": {"media": media_context(event, [("frame-1", "image/png", b"image")]),
                               "detector_observations": []}}}}]}


def labels(**states):
    return [{"event_id": "ev", "reviewer": "synthetic-test-reviewer", "clip_reviewed": True, "expected": states}]


def test_accuracy_distinct_from_schema_and_false_present_count(scene_payload):
    payload = scene_payload(flames="present")
    result = evaluate(job(payload), labels(flames="unknown", visible_forest_burning="unknown"))
    assert result["invalid_output_count"] == 0
    assert result["state_accuracy"] == .5
    assert result["false_present_count"] == 1
    assert result["passed"] is False


def test_invalid_output_counts_as_failure_not_omitted(scene_payload):
    payload = scene_payload(flames="present")
    payload["features"]["flames"]["evidence"][0]["asset_id"] = "other"
    result = evaluate(job(payload), labels(flames="present"))
    assert result["invalid_output_count"] == 1 and result["state_accuracy"] == 0


def test_human_review_required_and_unknown_is_not_absent(scene_payload):
    result = evaluate(job(scene_payload()), labels(flames="absent"))
    assert result["state_accuracy"] == 0
    with pytest.raises(ValueError, match="human_reviewed"):
        evaluate(job(scene_payload()), [])
    unreviewed = labels(flames="unknown")
    unreviewed[0]["clip_reviewed"] = False
    with pytest.raises(ValueError, match="human_clip_review"):
        evaluate(job(scene_payload()), unreviewed)


def test_query_does_not_promote_unknown_forest_burning_or_free_text(scene_payload):
    payload = scene_payload(flames="present")
    payload["description"] = "산불 발생 및 과실 확정이라는 잘못된 자유 문장"
    payload["features"]["mountain_road"] = dict(payload["features"]["flames"])
    query = build_retrieval_query(to_rag_input(SceneFacts.model_validate(payload), {"event_id": "ev"}))
    assert "차량 불꽃" in query and "산간 도로" in query
    assert "산림 연소" not in query and "과실" not in query


def test_only_present_with_evidence_becomes_query_feature():
    query = build_retrieval_query({"schema_version": "scene-facts-v2", "features": {
        "smoke": {"state": "present", "evidence": []},
        "flames": {"state": "absent", "evidence": [{}]},
        "visible_forest_burning": {"state": "unknown", "evidence": []}}})
    assert "연기" not in query and "화재" not in query and "산림 연소" not in query
