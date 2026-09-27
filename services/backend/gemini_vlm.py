import json
from typing import Any

from pydantic import BaseModel, Field


class Observation(BaseModel):
    text: str
    evidence_asset_ids: list[str]
    source_times_seconds: list[float] = Field(default_factory=list)


class GeminiResult(BaseModel):
    summary: str
    observations: list[Observation]
    uncertainties: list[str]


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
            "녹화 CCTV의 사고 의심 구간을 관찰하세요. 사고 여부·원인·과실·피해를 확정하지 마세요. "
            "화면에서 직접 관찰한 내용과 불확실성을 분리하고, observations에는 제공된 evidence_asset_ids만 사용하세요. "
            "source_times_seconds에는 영상 시작 기준 원본 시각(초)을 쓰고 화면에 없는 정보는 추측하지 마세요.\n"
            f"event_id={event['event_id']}, start_seconds={event['start_seconds']}, "
            f"end_seconds={event['end_seconds']}, object_observations="
            f"{json.dumps(event.get('object_observations', []), ensure_ascii=False)}\n"
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
        return {
            "status": "completed",
            **result.model_dump(),
            "provider_model": self.model,
            "prompt_version": "cctv-observation-v1",
        }
