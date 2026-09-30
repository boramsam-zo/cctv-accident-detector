"""Gemini SDK 경계와 VLM에서 RAG로 넘기는 데이터 검증을 확인한다."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from services.backend.gemini_vlm import (
    PROMPT2, PROMPT_PRESETS, PROMPT_VERSION1, GeminiResult, GeminiVLM,
)


def response_data(**changes):
    """필드별 검증에 사용할 기본 Gemini 응답 JSON을 만든다."""
    value = {
        "description": "차량 두 대가 가까워집니다. 접촉 여부는 불분명합니다.",
        "operator_confirmed": None,
        "scene_conditions": {"day_time": "day", "weather": None},
        "involved_objects": [{"type": "Car", "count": 2}],
        "accident_type": None,
        "lane_blocked": None,
        "affected_person_visible": False,
        "fire_visible": False,
        "observations": [{"text": "차량 두 대가 보입니다.", "evidence_asset_ids": ["frame-1"],
                          "source_times_seconds": []}],
        "uncertainties": ["접촉 여부가 보이지 않습니다."],
    }
    return {**value, **changes}


def make_vlm(payload):
    """지정한 JSON을 반환하도록 Gemini SDK 호출을 mock 처리한다."""
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(payload))
    return GeminiVLM("", "test-model", client), client


def event():
    """Modal 추론이 제공한 후보 이벤트 메타데이터를 만든다."""
    return {"event_id": "event-1", "candidate_time_s": 4.0,
            "start_seconds": 3.0, "end_seconds": 5.0, "object_observations": []}


def test_sdk_receives_structured_schema_and_rag_keeps_candidate_metadata():
    """SDK 요청 스키마와 RAG 입력의 원본 후보 시각·ID 보존을 확인한다."""
    vlm, client = make_vlm(response_data())

    result = vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])

    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["config"] == {"response_mime_type": "application/json", "response_schema": GeminiResult}
    assert "candidate_time_s=4.0" in request["contents"][0]
    assert "Pedestrian, Car, Truck, Bus, Motorcycle, Bicycle, Dynamic" in request["contents"][0]
    assert "rear-end, head-on, sideswipe, t-bone, single" in request["contents"][0]
    assert "clear, cloudy, rain, snow, fog" in request["contents"][0]
    assert len(request["contents"]) == 2
    assert result["rag_input"]["event_id"] == "event-1"
    assert result["rag_input"]["candidate_time_s"] == 4.0
    assert result["rag_input"]["operator_confirmed"] is None
    assert "camera_id" not in result["rag_input"]
    assert result["raw_output"]["description"] == response_data()["description"]
    assert result["request"]["model"] == "test-model"
    assert result["request"]["media_asset_ids"] == ["frame-1"]


def test_model_connection_check_requires_nonempty_response():
    vlm, client = make_vlm(response_data())

    result = vlm.check("gemini-check-model")

    request = client.models.generate_content.call_args.kwargs
    assert request == {"model": "gemini-check-model", "contents": "Connection check. Reply with OK."}
    assert result["model"] == "gemini-check-model"
    assert result["response_preview"]


def test_sdk_uses_per_job_model_and_prepends_custom_prompt():
    vlm, client = make_vlm(response_data())

    result = vlm.analyze(
        event(),
        [("frame-1", "image/png", b"image-bytes")],
        model="gemini-test-selected",
        prompt_override="정지한 차량 수를 우선 확인하세요.",
    )

    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "gemini-test-selected"
    assert request["contents"][0].startswith("사용자 추가 지시:\n정지한 차량 수를 우선 확인하세요.")
    assert "필수 출력 및 판정 규칙:" in request["contents"][0]
    assert result["provider_model"] == "gemini-test-selected"
    assert result["prompt_version"].startswith("custom-")


def test_sdk_can_replace_default_prompt_but_keeps_event_context():
    vlm, client = make_vlm(response_data())

    vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")],
                prompt_override="사고 여부만 판정하세요.", prompt_mode="replace")

    prompt = client.models.generate_content.call_args.kwargs["contents"][0]
    assert prompt.startswith("사고 여부만 판정하세요.\nevent_id=event-1")
    assert "사용자 추가 지시" not in prompt
    assert "candidate_time_s=4.0" in prompt


def test_saved_prompt_presets_have_stable_ids_and_prompt2_version():
    assert [preset["id"] for preset in PROMPT_PRESETS] == ["version1", "prompt2"]
    assert PROMPT_PRESETS[0]["prompt"] == PROMPT_VERSION1
    assert PROMPT_PRESETS[1]["prompt"] == PROMPT2

    vlm, _ = make_vlm(response_data())
    result = vlm.analyze(
        event(), [("frame-1", "image/png", b"image-bytes")],
        prompt_override=PROMPT2, prompt_mode="replace",
    )
    assert result["prompt_version"] == "prompt2"


@pytest.mark.parametrize("changes", [
    {"scene_conditions": {"day_time": "unknown", "weather": None}},
    {"scene_conditions": {"day_time": "twilight", "weather": None}},
    {"scene_conditions": {"day_time": "day", "weather": "wet"}},
    {"scene_conditions": {"day_time": "day", "weather": "sunset"}},
    {"scene_conditions": {"day_time": "day", "weather": "Rain"}},
    {"involved_objects": [{"type": "Car", "count": 0}]},
    {"involved_objects": [{"type": "Van", "count": 1}]},
    {"involved_objects": [{"type": "car", "count": 1}]},
    {"operator_confirmed": "uncertain"},
    {"accident_type": "rear_end"},
    {"accident_type": "추돌"},
    {"accident_type": "Collision"},
])
def test_rejects_gemini_values_outside_contract(changes):
    """허용되지 않은 환경·객체 수·확인 값은 스키마 검증에서 거부하는지 확인한다."""
    vlm, _ = make_vlm(response_data(**changes))
    with pytest.raises(ValidationError):
        vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])


def test_rejects_unprovided_evidence_reference():
    """제공하지 않은 근거 asset ID를 Gemini가 인용하면 거부하는지 확인한다."""
    payload = response_data(observations=[{"text": "차량", "evidence_asset_ids": ["other-frame"]}])
    vlm, _ = make_vlm(payload)
    with pytest.raises(ValueError, match="invalid_evidence_asset_id"):
        vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])


@pytest.mark.parametrize("class_name", ["Pedestrian", "Car", "Truck", "Bus", "Motorcycle", "Bicycle", "Dynamic"])
def test_accepts_each_allowed_object_type(class_name):
    """YOLO의 일곱 탐지 타입이 정확한 표기로 응답에 유지되는지 확인한다."""
    vlm, _ = make_vlm(response_data(involved_objects=[{"type": class_name, "count": 1}]))
    result = vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])
    assert result["rag_input"]["involved_objects"] == [{"type": class_name, "count": 1}]


@pytest.mark.parametrize("accident_type", ["rear-end", "head-on", "sideswipe", "t-bone", "single", None])
def test_accepts_documented_accident_types(accident_type):
    """다섯 사고 유형과 사고 확인 불가 시 null만 유지하는지 확인한다."""
    vlm, _ = make_vlm(response_data(accident_type=accident_type))
    result = vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])
    assert result["rag_input"]["accident_type"] == accident_type


@pytest.mark.parametrize("day_time,weather", [
    ("day", "clear"), ("day", "cloudy"), ("day", "rain"),
    ("night", "snow"), ("night", "fog"), (None, None),
])
def test_accepts_requested_weather_labels(day_time, weather):
    """요청한 다섯 장면 상태와 판단 불가 null이 RAG 입력에 유지되는지 확인한다."""
    vlm, _ = make_vlm(response_data(scene_conditions={"day_time": day_time, "weather": weather}))
    result = vlm.analyze(event(), [("frame-1", "image/png", b"image-bytes")])
    assert result["rag_input"]["scene_conditions"]["weather"] == weather


def test_both_prompt_presets_include_scene_condition_contract():
    for prompt in (PROMPT_VERSION1, PROMPT2):
        assert "day 또는 night" in prompt
        assert "clear, cloudy, rain, snow, fog" in prompt
        assert "위 목록에 없는 값은 절대 생성하지 마세요" in prompt


def test_does_not_call_gemini_without_media():
    """clip·frame이 없을 때 외부 Gemini 호출을 막는지 확인한다."""
    vlm, client = make_vlm(response_data())
    with pytest.raises(ValueError, match="no_evidence_media"):
        vlm.analyze(event(), [])
    client.models.generate_content.assert_not_called()
