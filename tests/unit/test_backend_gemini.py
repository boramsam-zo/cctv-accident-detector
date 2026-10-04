import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from services.backend.gemini_vlm import GeminiResult, GeminiVLM, PROMPT_PRESETS, SCENE_FACTS_PROMPT


def run(payload, *, event=None, media=None, **kwargs):
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(payload))
    vlm = GeminiVLM("", "test-model", client)
    event = event or {"event_id": "event-1", "candidate_time_s": 4,
        "evidence": {"clip_asset_id": "clip-1", "clip_start_seconds": 3, "clip_end_seconds": 5,
                     "frames": [{"asset_id": "frame-1", "source_time_seconds": 4}]}}
    media = media if media is not None else [("clip-1", "video/mp4", b"clip"), ("frame-1", "image/png", b"image")]
    return vlm.analyze(event, media, **kwargs), client


def test_structured_input_maps_parts_and_keeps_unknown(scene_payload):
    result, client = run(scene_payload(flames="present"))
    request = client.models.generate_content.call_args.kwargs
    expected_schema = GeminiResult.model_json_schema()
    expected_schema["$defs"]["Evidence"]["properties"]["asset_id"]["enum"] = ["clip-1", "frame-1"]
    assert request["config"]["response_json_schema"] == expected_schema
    assert request["config"]["response_json_schema"]["additionalProperties"] is False
    version = request["config"]["response_json_schema"]["properties"]["schema_version"]
    assert version["enum"] == ["scene-facts-v2"] and "const" not in version
    asserted = request["config"]["response_json_schema"]["$defs"]["AssertedFact"]
    assert asserted["properties"]["evidence"]["minItems"] == 1
    assert [item["part_index"] for item in result["request"]["input"]["media"]] == [1, 2]
    assert result["request"]["input"]["media"][0]["clip_start_seconds"] == 3
    assert result["request"]["input"]["media"][1]["source_time_seconds"] == 4
    assert result["rag_input"]["operator_confirmed"] is None
    assert result["rag_input"]["fire_visible"] is True
    assert result["rag_input"]["features"]["visible_forest_burning"]["state"] == "unknown"
    assert result["validation"]["visual_accuracy"] == "not_evaluated"
    assert result["prompt_version"] == "scene-facts-v2"


@pytest.mark.parametrize("mode", ["replace", "prepend"])
def test_custom_prompt_cannot_remove_contract(scene_payload, mode):
    result, client = run(scene_payload(), prompt_override="화재를 확인하세요", prompt_mode=mode, model="selected")
    prompt = client.models.generate_content.call_args.kwargs["contents"][0]
    assert SCENE_FACTS_PROMPT in prompt and "input JSON:" in prompt
    assert result["provider_model"] == "selected"
    assert result["prompt_version"].startswith("custom-")
    assert PROMPT_PRESETS[0]["id"] == "scene-facts-v2"


@pytest.mark.parametrize("state,expected", [("present", True), ("absent", False), ("unknown", None)])
def test_vlm_assessment_alias_preserves_three_states(scene_payload, state, expected):
    result, _ = run(scene_payload(accident=state))
    assert result["rag_input"]["operator_confirmed"] is expected


def test_rejects_asserted_fact_without_evidence_and_extra_fields(scene_payload):
    payload = scene_payload(flames="present")
    payload["features"]["flames"]["evidence"] = []
    with pytest.raises(ValidationError):
        run(payload)
    payload = scene_payload()
    payload["agency"] = "소방"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        run(payload)


@pytest.mark.parametrize("ref,reason", [
    ({"asset_id": "other", "clip_time_seconds": None, "source_time_seconds": None}, "invalid_evidence_asset_id"),
    ({"asset_id": "frame-1", "clip_time_seconds": None, "source_time_seconds": 8}, "invalid_frame_source_time"),
    ({"asset_id": "frame-1", "clip_time_seconds": 1, "source_time_seconds": 4}, "frame_has_no_clip_time"),
    ({"asset_id": "clip-1", "clip_time_seconds": 3, "source_time_seconds": None}, "invalid_clip_time"),
    ({"asset_id": "clip-1", "clip_time_seconds": 1, "source_time_seconds": 3}, "inconsistent_evidence_time_mapping"),
    ({"asset_id": "clip-1", "clip_time_seconds": None, "source_time_seconds": 6}, "invalid_clip_source_time"),
])
def test_rejects_invented_assets_and_times(scene_payload, ref, reason):
    payload = scene_payload(flames="present")
    payload["features"]["flames"]["evidence"] = [ref]
    with pytest.raises(ValueError, match=reason):
        run(payload)


def test_accepts_consistent_clip_time_mapping(scene_payload):
    payload = scene_payload(flames="present")
    payload["features"]["flames"]["evidence"] = [{"asset_id": "clip-1", "clip_time_seconds": 1, "source_time_seconds": 4}]
    result, _ = run(payload)
    assert result["validation"]["provenance"] == "passed"


@pytest.mark.parametrize("accident", ["unknown", "absent"])
def test_ambiguous_accident_cannot_have_type(scene_payload, accident):
    payload = scene_payload(accident=accident)
    payload["accident_type"] = "rear-end"
    payload["accident_type_evidence"] = [{"asset_id": "frame-1", "clip_time_seconds": None, "source_time_seconds": None}]
    with pytest.raises(ValidationError, match="accident_type_requires"):
        run(payload)


def test_dynamic_requires_detector_support(scene_payload):
    payload = scene_payload()
    payload["involved_objects"] = [{"type": "Dynamic", "count": 1,
        "evidence": [{"asset_id": "frame-1", "clip_time_seconds": None, "source_time_seconds": None}]}]
    with pytest.raises(ValueError, match="dynamic_requires_detector_evidence"):
        run(payload)


def test_missing_mapping_cannot_generate_source_time(scene_payload):
    payload = scene_payload(flames="present")
    payload["features"]["flames"]["evidence"][0]["source_time_seconds"] = 4
    with pytest.raises(ValueError, match="invalid_frame_source_time"):
        run(payload, event={"event_id": "e", "evidence": {}})


def test_no_media_blocks_model_call(scene_payload):
    with pytest.raises(ValueError, match="no_evidence_media"):
        run(scene_payload(), media=[])


def test_connection_check():
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(text="OK")
    assert GeminiVLM("", "m", client).check()["response_preview"] == "OK"


@pytest.mark.parametrize("field,value", [("day_time", "twilight"), ("weather", "wet"), ("weather", "Rain")])
def test_provider_cannot_invent_environment_labels(scene_payload, field, value):
    payload = scene_payload()
    payload["scene_conditions"][field] = value
    with pytest.raises(ValidationError):
        run(payload)


def test_known_weather_needs_evidence(scene_payload):
    payload = scene_payload()
    payload["scene_conditions"]["weather"] = "rain"
    with pytest.raises(ValidationError, match="scene_condition_requires_evidence"):
        run(payload)


def test_provider_version_drift_is_rejected(scene_payload):
    payload = scene_payload()
    payload["schema_version"] = "v2.0"
    with pytest.raises(ValidationError, match="literal_error"):
        run(payload)


def test_empty_connection_response_is_failure():
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(text="")
    with pytest.raises(ValueError, match="empty_gemini_response"):
        GeminiVLM("", "m", client).check()
