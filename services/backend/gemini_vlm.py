import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class Observation(BaseModel):
    text: str
    evidence_asset_ids: list[str]
    source_times_seconds: list[float] = Field(default_factory=list)


class SceneConditions(BaseModel):
    day_time: Literal["day", "night", "twilight"] | None = Field(
        description="화면만으로 구분 가능한 주간, 야간, 황혼. 판단 불가 시 null")
    weather: str | None = Field(description="화면에서 직접 확인되는 기상만 기록. 불명확하면 null")


class InvolvedObject(BaseModel):
    type: str = Field(description="사고에 관여한 것으로 보이는 객체 종류")
    count: int = Field(ge=1, description="해당 종류에서 실제로 확인되는 객체 수")


class GeminiResult(BaseModel):
    description: str = Field(description="확인된 장면을 한국어로 짧게 설명하고 불확실성을 명시")
    scene_conditions: SceneConditions
    involved_objects: list[InvolvedObject]
    accident_type: str | None = Field(description="충돌 유형이 영상에서 확인될 때만 기록")
    lane_blocked: bool | None = Field(description="차로 점유 여부. 판단 불가 시 null")
    affected_person_visible: bool | None = Field(description="사고 영향을 받은 사람이 보이는지. 판단 불가 시 null")
    fire_visible: bool | None = Field(description="화재가 보이는지. 판단 불가 시 null")
    observations: list[Observation]
    uncertainties: list[str]


class RagInput(BaseModel):
    event_id: str
    camera_id: str | None
    candidate_time_s: float | None
    description: str
    scene_conditions: SceneConditions
    involved_objects: list[InvolvedObject]
    accident_type: str | None
    lane_blocked: bool | None
    affected_person_visible: bool | None
    fire_visible: bool | None
    operator_confirmed: bool | None


class GeminiVLM:
    def __init__(self, api_key: str, model: str, client: Any = None):
        if not api_key and client is None:
            raise ValueError("GEMINI_API_KEY is required")
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self.client = client
        self.model = model

    def analyze(self, event: dict, media: list[tuple[str, str, bytes]]) -> dict:
        from google.genai import types

        if not media:
            raise ValueError("no_evidence_media")
        allowed_ids = {asset_id for asset_id, _, _ in media}
        prompt = (
            "녹화 CCTV의 사고 의심 후보 구간과 대표 이미지를 관찰하고 RAG 검색에 쓸 장면 정보를 JSON으로 작성하세요. "
            "description은 한국어 1~2문장으로 쓰고 관찰과 추정을 구분하세요. 사고 여부, 책임, 과실, 피해를 확정하지 마세요. "
            "scene_conditions.day_time은 영상에서 명확할 때 day/night/twilight로, weather는 비·눈 등 기상이 실제 보일 때만 적으세요. "
            "노면이 젖어 보이는 것만으로 비가 온다고 추론하지 마세요. 불확실하면 null입니다. "
            "involved_objects는 사고에 관여한 것으로 보이는 객체만 종류별로 세고, 화면 밖 객체를 추가하지 마세요. "
            "accident_type은 접촉 방향이 확인될 때만 적고, 단순 접근·정지만 보이면 null입니다. "
            "lane_blocked, affected_person_visible, fire_visible은 관찰 가능할 때 true/false, 판단 불가 시 null입니다. "
            "특히 사람이 단순히 보이는 것과 사고 영향을 받은 사람은 구분하세요. "
            "observations의 evidence_asset_ids에는 제공된 ID만 사용하고, source_times_seconds는 확인 가능한 원본 영상 시각만 사용하세요. "
            "클립 내부 시각을 원본 시각으로 추측해 변환하지 마세요. 모호한 점은 uncertainties에 적으세요.\n"
            f"event_id={event['event_id']}, start_seconds={event.get('start_seconds')}, "
            f"end_seconds={event.get('end_seconds')}, candidate_time_s={event.get('candidate_time_s')}, "
            f"object_observations={json.dumps(event.get('object_observations', []), ensure_ascii=False)}\n"
            f"media IDs={sorted(allowed_ids)}"
        )
        parts = [types.Part.from_bytes(data=data, mime_type=mime) for _, mime, data in media]
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt, *parts],
            config={"response_mime_type": "application/json", "response_schema": GeminiResult},
        )
        result = GeminiResult.model_validate_json(response.text)
        for observation in result.observations:
            if not observation.evidence_asset_ids or not set(observation.evidence_asset_ids) <= allowed_ids:
                raise ValueError("invalid_evidence_asset_id")
        rag_input = RagInput.model_validate({
            "event_id": event["event_id"],
            "camera_id": event.get("camera_id"),
            "candidate_time_s": event.get("candidate_time_s"),
            "description": result.description,
            "scene_conditions": result.scene_conditions.model_dump(),
            "involved_objects": [item.model_dump() for item in result.involved_objects],
            "accident_type": result.accident_type,
            "lane_blocked": result.lane_blocked,
            "affected_person_visible": result.affected_person_visible,
            "fire_visible": result.fire_visible,
            "operator_confirmed": None,
        }).model_dump()
        return {
            "status": "completed",
            "summary": result.description,
            "observations": [item.model_dump() for item in result.observations],
            "uncertainties": result.uncertainties,
            "rag_input": rag_input,
            "provider_model": self.model,
            "prompt_version": "cctv-rag-scene-v1",
        }
