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
    weather: Literal["clear", "sunset", "night", "wet", "rain"] | None = Field(
        description="영상에서 확인한 장면 상태: 맑음, 해질녘, 야간, 젖은 노면, 강수. 판단 불가 시 null")


class InvolvedObject(BaseModel):
    type: Literal["Pedestrian", "Car", "Truck", "Bus", "Motorcycle", "Bicycle", "Dynamic"] = Field(
        description="영상에서 확인된 관련 객체의 YOLO 탐지 클래스명. 이 일곱 값만 사용")
    count: int = Field(ge=1, description="해당 종류에서 실제로 확인되는 객체 수")


class GeminiResult(BaseModel):
    description: str = Field(description="확인된 장면을 한국어로 짧게 설명하고 불확실성을 명시")
    operator_confirmed: bool | None = Field(
        description="Gemini의 사고 의심 재확인. 사고 장면이 보이면 true, 정상 장면이 명확하면 false, 판단 불가 시 null")
    scene_conditions: SceneConditions
    involved_objects: list[InvolvedObject]
    accident_type: Literal["rear-end", "head-on", "sideswipe", "t-bone", "single"] | None = Field(
        description="영상에서 확인한 사고와 가장 가까운 유형. 정상 장면이거나 유형을 구분할 근거가 부족하면 null")
    lane_blocked: bool | None = Field(description="차로 점유 여부. 판단 불가 시 null")
    affected_person_visible: bool | None = Field(description="사고 영향을 받은 사람이 보이는지. 판단 불가 시 null")
    fire_visible: bool | None = Field(description="화재가 보이는지. 판단 불가 시 null")
    observations: list[Observation]
    uncertainties: list[str]


class RagInput(BaseModel):
    event_id: str
    candidate_time_s: float | None
    description: str
    scene_conditions: SceneConditions
    involved_objects: list[InvolvedObject]
    accident_type: Literal["rear-end", "head-on", "sideswipe", "t-bone", "single"] | None
    lane_blocked: bool | None
    affected_person_visible: bool | None
    fire_visible: bool | None
    operator_confirmed: bool | None


class GeminiVLM:
    def __init__(self, api_key: str, model: str, client: Any = None):
        """지정한 모델과 API 키 또는 주입된 Gemini 클라이언트를 설정한다."""
        if not api_key and client is None:
            raise ValueError("GEMINI_API_KEY is required")
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self.client = client
        self.model = model

    def analyze(self, event: dict, media: list[tuple[str, str, bytes]]) -> dict:
        """후보 영상·이미지를 분석하고 검증된 장면 설명과 RAG 입력을 만든다."""
        from google.genai import types

        if not media:
            raise ValueError("no_evidence_media")
        allowed_ids = {asset_id for asset_id, _, _ in media}
        prompt = (
            "녹화 CCTV의 사고 의심 후보 구간과 대표 이미지를 관찰하고 RAG 검색에 쓸 장면 정보를 JSON으로 작성하세요. "
            "description은 한국어 1~2문장으로 쓰고 관찰과 추정을 구분하세요. 사고 원인을 추측하지 말고 책임, 과실, 피해를 확정하지 마세요. "
            "X3D-S가 후보로 골랐더라도 실제 영상이 정상일 수 있습니다. operator_confirmed는 Gemini의 독립적인 장면 재확인 값입니다. "
            "충돌·전도 등 사고로 볼 만한 장면이 직접 보이면 true, 사고 없이 정상 주행·정차하는 장면이 명확하면 false, "
            "클립이 짧거나 가려져 구분할 수 없으면 null을 반환하세요. 후보 점수만으로 true를 선택하지 마세요. "
            "scene_conditions.day_time은 영상에서 명확할 때 day/night/twilight로 적으세요. "
            "scene_conditions.weather는 영상에서 확인한 상태 중 clear, sunset, night, wet, rain 하나만 소문자로 적으세요. "
            "rain은 현재 비가 내리는 모습이 보일 때, wet은 비가 내리는 모습 없이 노면이 젖은 것이 보일 때 사용하세요. "
            "night는 야간, sunset은 해질녘, clear는 주간에 맑고 마른 상태가 확인될 때 사용하세요. "
            "여러 조건이 보이면 rain, wet, night, sunset, clear 순서로 가장 앞선 값을 선택하세요. "
            "젖은 노면만으로 현재 비가 온다고 추론하지 말고, 상태를 구분할 수 없으면 null을 반환하세요. "
            "involved_objects에는 제공된 영상에서 사고에 관여한 것으로 확인되는 객체만 넣으세요. "
            "type은 Pedestrian, Car, Truck, Bus, Motorcycle, Bicycle, Dynamic 중 하나를 대소문자까지 정확히 사용하세요. "
            "다른 단어나 한국어 이름을 사용하지 마세요. 탐지되지 않았거나 관여 여부가 불명확한 종류는 추가하지 말고, 해당 객체가 없으면 빈 배열을 반환하세요. "
            "object_observations는 Modal의 YOLO 탐지 근거이지만 같은 객체가 여러 프레임에 반복될 수 있으므로 박스 수를 객체 수로 더하지 마세요. "
            "count는 영상에서 구분 가능한 관련 객체의 수만 적고 화면 밖 객체를 추측하지 마세요. "
            "Dynamic은 뜻이 확정되지 않은 모델 라벨이므로 object_observations에 Dynamic 탐지가 있을 때만 사용하고 움직이는 객체를 임의로 Dynamic으로 분류하지 마세요. "
            "accident_type은 확인된 사고 장면과 가장 가까운 유형을 영어 rear-end, head-on, sideswipe, t-bone, single 중 하나로만 반환하세요. "
            "rear-end는 뒤따르던 차량의 앞부분이 앞 차량의 뒷부분에 충돌한 경우, head-on은 마주 보는 두 차량의 앞부분이 충돌한 경우, "
            "sideswipe는 나란히 이동하는 객체 사이의 측면 접촉, t-bone은 한 객체의 앞부분이 다른 객체의 측면에 충돌한 경우입니다. "
            "single은 다른 도로 이용자와의 충돌 없이 한 차량만 관련된 사고입니다. "
            "영상에 사고가 보이지만 정확한 충돌 형태가 불명확하면 가장 가까운 유형을 고르고 description과 uncertainties에 근거와 불확실성을 적으세요. "
            "정상 장면이거나 사고 자체를 확인할 수 없으면 accident_type은 null로 두세요. "
            "X3D-S 후보 점수만으로 사고 유형을 정하거나 영상에 없는 충돌 방향을 추측하지 마세요. "
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
            "candidate_time_s": event.get("candidate_time_s"),
            "description": result.description,
            "scene_conditions": result.scene_conditions.model_dump(),
            "involved_objects": [item.model_dump() for item in result.involved_objects],
            "accident_type": result.accident_type,
            "lane_blocked": result.lane_blocked,
            "affected_person_visible": result.affected_person_visible,
            "fire_visible": result.fire_visible,
            "operator_confirmed": result.operator_confirmed,
        }).model_dump()
        return {
            "status": "completed",
            "summary": result.description,
            "observations": [item.model_dump() for item in result.observations],
            "uncertainties": result.uncertainties,
            "rag_input": rag_input,
            "provider_model": self.model,
            "prompt_version": "cctv-rag-scene-v2",
        }
