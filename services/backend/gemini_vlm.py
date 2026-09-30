import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


PROMPT_VERSION1 = (
    "녹화 CCTV의 사고 의심 후보 구간과 대표 이미지를 관찰하고 RAG 검색에 쓸 장면 정보를 JSON으로 작성하세요. "
    "description은 한국어 1~2문장으로 쓰고 관찰과 추정을 구분하세요. 사고 원인을 추측하지 말고 책임, 과실, 피해를 확정하지 마세요. "
    "X3D-S가 후보로 골랐더라도 실제 영상이 정상일 수 있습니다. operator_confirmed는 Gemini의 독립적인 장면 재확인 값입니다. "
    "충돌·전도 등 사고로 볼 만한 장면이 직접 보이면 true, 사고 없이 정상 주행·정차하는 장면이 명확하면 false, "
    "클립이 짧거나 가려져 구분할 수 없으면 null을 반환하세요. 후보 점수만으로 true를 선택하지 마세요. "
    "scene_conditions.day_time은 영상에서 명확할 때 day 또는 night만 적고, 판별할 수 없으면 null을 반환하세요. "
    "scene_conditions.weather는 영상에서 명확할 때 clear, cloudy, rain, snow, fog 중 하나만 소문자로 적고, 판별할 수 없으면 null을 반환하세요. "
    "젖은 노면이나 어두운 화면만으로 날씨를 추론하지 말고 목록 밖의 값을 생성하지 마세요. "
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
    "클립 내부 시각을 원본 시각으로 추측해 변환하지 마세요. 모호한 점은 uncertainties에 적으세요."
)


PROMPT2 = """제공된 원본 사고 후보 영상과 빨간 충돌 후보 박스가 표시된 대표 이미지를 분석하세요.

목표는 일반 장면 묘사가 아니라, 후속 RAG 시스템이 현장 대응 매뉴얼과 대한민국 교통법규·판례를 정확하게 검색할 수 있도록 사고 사실을 기존 JSON 스키마에 맞춰 작성하는 것입니다. 새로운 필드는 추가하지 마세요.

[사고 재확인]
- 충돌, 접촉, 전도 또는 충돌 직후의 급격한 움직임이 직접 확인되면 operator_confirmed=true입니다.
- 정상 주행이나 정차만 확인되면 false, 가림·화질·짧은 구간 때문에 판단할 수 없으면 null입니다.
- X3D 후보 점수와 빨간 박스만으로 사고를 확정하지 마세요. 빨간 박스는 실제 충돌 위치가 아니라 참고 영역입니다.

[description]
한국어 3~5문장으로 다음 내용을 가능한 범위에서 순서대로 포함하세요.
1. 사고 유형과 참여 객체
2. 사고 직전 각 객체의 움직임
3. 충돌 방향과 충돌 부위
4. 교차로, 횡단보도, 정지선, 중앙선, 차로 등 도로 구조
5. 차량·보행자 신호의 가시 상태
6. 충돌 후 정지·이탈·차로 점유 상태
7. 사람, 화재, 연기, 파편 및 2차 사고 위험
8. 대응 매뉴얼과 법령 검색에 사용할 관찰 키워드

마지막 문장은 반드시 "검색 단서: 키워드1, 키워드2" 형식으로 작성하세요. 영상에서 직접 확인된 경우에만 교차로 사고, 횡단보도 인접 사고, 보행자 관련 사고, 후방추돌, 측면충돌, 정면충돌, 차로변경 중 충돌, 중앙선 인접 사고, 정지 차량 추돌, 신호 상태 확인 필요, 안전거리 관련, 차로 점유, 파편 발생, 2차 사고 위험, 사고 후 차량 정지, 사고 후 차량 이탈 가능성, 구호 조치 필요 가능성, 경찰 신고 검토, 소방·구급 요청 검토 등의 표현을 사용하세요.

법률 위반, 가해자, 피해자, 과실 비율을 확정하지 마세요. 신호위반, 중앙선 침범, 과속, 안전거리 미확보처럼 영상만으로 확정하기 어려운 사항은 "관련 여부 확인 필요"로 작성하세요.

[기존 필드]
- accident_type은 rear-end, head-on, sideswipe, t-bone, single 중 가장 가까운 값만 사용하고, 사고가 확인되지 않으면 null입니다.
- involved_objects에는 사고에 실제로 관여한 객체만 넣고 type은 Pedestrian, Car, Truck, Bus, Motorcycle, Bicycle, Dynamic 중 하나만 사용하세요.
- lane_blocked는 사고 차량이나 파편이 차로를 막으면 true, 명확히 막지 않으면 false, 판단 불가하면 null입니다.
- affected_person_visible은 사고 영향을 받은 사람이 보이는 경우에만 true입니다.
- fire_visible은 불꽃이나 화재가 직접 보이는 경우에만 true입니다.
- scene_conditions.day_time은 영상에서 확인 가능한 경우 day 또는 night만 입력하고, 판단할 수 없으면 null을 입력하세요.
- scene_conditions.weather는 영상에서 확인 가능한 경우 clear, cloudy, rain, snow, fog 중 하나만 입력하고, 판단할 수 없으면 null을 입력하세요.

[근거와 불확실성]
- observations에는 사고 판단, 객체 움직임, 도로 구조, 충돌 후 위험 요소를 가능한 한 각각 분리해 작성하세요.
- evidence_asset_ids에는 제공된 ID만 사용하고 source_times_seconds는 확인 가능한 원본 영상 시각만 사용하세요.
- uncertainties에는 신호 상태·적용 방향, 실제 속도, 제한속도, 정확한 충돌 부위, 부상 여부, 탑승자 상태, 신고·구호 여부, 차선 종류 등 확인할 수 없는 항목을 구체적으로 기록하세요.
- 확인되지 않은 정보는 추측하지 마세요."""


SCENE_CONDITIONS_CONTRACT = """

[scene_conditions 필수 값 제한 - 이 규칙을 앞선 설명보다 우선 적용]
- scene_conditions.day_time은 영상에서 명확히 판별할 수 있을 때 day 또는 night만 사용하고, 판별할 수 없으면 null을 사용하세요.
- scene_conditions.weather는 영상에서 명확히 판별할 수 있을 때 clear, cloudy, rain, snow, fog 중 하나만 사용하고, 판별할 수 없으면 null을 사용하세요.
- 위 목록에 없는 값은 절대 생성하지 마세요. twilight, sunset, wet 등 유사한 표현도 사용하지 마세요.
"""

PROMPT_VERSION1 = f"{PROMPT_VERSION1}{SCENE_CONDITIONS_CONTRACT}"
PROMPT2 = f"{PROMPT2}{SCENE_CONDITIONS_CONTRACT}"

DEFAULT_ANALYSIS_PROMPT = PROMPT_VERSION1
PROMPT_PRESETS = (
    {"id": "version1", "name": "version1 · 기존 장면 분석", "prompt": PROMPT_VERSION1},
    {"id": "prompt2", "name": "prompt2 · 대응 매뉴얼·교통법 RAG", "prompt": PROMPT2},
)


class Observation(BaseModel):
    text: str
    evidence_asset_ids: list[str]
    source_times_seconds: list[float] = Field(default_factory=list)


class SceneConditions(BaseModel):
    day_time: Literal["day", "night"] | None = Field(
        description="영상에서 판별한 시간대: day 또는 night. 판별 불가 시 null")
    weather: Literal["clear", "cloudy", "rain", "snow", "fog"] | None = Field(
        description="영상에서 판별한 날씨: clear, cloudy, rain, snow, fog. 판별 불가 시 null")


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

    def check(self, model: str | None = None) -> dict:
        """선택 모델에 최소 텍스트 요청을 보내 현재 응답 가능 여부를 확인한다."""
        selected_model = model or self.model
        response = self.client.models.generate_content(
            model=selected_model,
            contents="Connection check. Reply with OK.",
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("empty_gemini_response")
        return {"model": selected_model, "response_preview": text[:120]}

    def analyze(self, event: dict, media: list[tuple[str, str, bytes]], *,
                model: str | None = None, prompt_override: str = "",
                prompt_mode: str = "prepend") -> dict:
        """후보 영상·이미지를 분석하고 검증된 장면 설명과 RAG 입력을 만든다."""
        from google.genai import types

        if not media:
            raise ValueError("no_evidence_media")
        allowed_ids = {asset_id for asset_id, _, _ in media}
        prompt = DEFAULT_ANALYSIS_PROMPT
        event_context = (
            f"event_id={event['event_id']}, start_seconds={event.get('start_seconds')}, "
            f"end_seconds={event.get('end_seconds')}, candidate_time_s={event.get('candidate_time_s')}, "
            f"object_observations={json.dumps(event.get('object_observations', []), ensure_ascii=False)}\n"
            f"media IDs={sorted(allowed_ids)}"
        )
        if prompt_override.strip():
            if prompt_mode == "replace":
                prompt = prompt_override.strip()
            else:
                prompt = f"사용자 추가 지시:\n{prompt_override.strip()}\n\n필수 출력 및 판정 규칙:\n{prompt}"
        prompt = f"{prompt}\n{event_context}"
        selected_model = model or self.model
        parts = [types.Part.from_bytes(data=data, mime_type=mime) for _, mime, data in media]
        response = self.client.models.generate_content(
            model=selected_model,
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
            "raw_output": result.model_dump(),
            "request": {"model": selected_model, "prompt": prompt,
                        "media_asset_ids": sorted(allowed_ids)},
            "observations": [item.model_dump() for item in result.observations],
            "uncertainties": result.uncertainties,
            "rag_input": rag_input,
            "provider_model": selected_model,
            "prompt_version": (
                "version1" if not prompt_override.strip() or prompt_override.strip() == PROMPT_VERSION1.strip()
                else "prompt2" if prompt_override.strip() == PROMPT2.strip()
                else f"custom-{hashlib.sha256(prompt_override.encode()).hexdigest()[:12]}"
            ),
        }
