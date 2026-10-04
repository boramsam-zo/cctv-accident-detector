"""Visual facts contract and server-side media provenance validation."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _singleton_enum(schema):
    """Emit single-value literals as provider-compatible enum constraints."""
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]


class Evidence(StrictModel):
    asset_id: str = Field(min_length=1)
    clip_time_seconds: float | None = Field(ge=0, strict=True)
    source_time_seconds: float | None = Field(ge=0, strict=True)


class AssertedFact(StrictModel):
    state: Literal["present", "absent"]
    evidence: list[Evidence] = Field(min_length=1, description="present/absent는 관찰 범위를 보여주는 근거가 최소 1개 필요")
    reason: str = Field(min_length=1)


class UnknownFact(StrictModel):
    state: Literal["unknown"] = Field(json_schema_extra=_singleton_enum)
    evidence: list[Evidence]
    reason: str = Field(min_length=1)


# anyOf exposes the evidence requirement to the generation schema, rather than
# leaving it only in a Python validator after the provider has generated JSON.
VisualFact = AssertedFact | UnknownFact


class Features(StrictModel):
    mountain_road: VisualFact
    visible_vegetation_near_fire: VisualFact
    flames: VisualFact
    smoke: VisualFact
    debris: VisualFact
    lane_blockage: VisualFact
    affected_people_visible: VisualFact
    visible_forest_burning: VisualFact


class SceneConditions(StrictModel):
    day_time: Literal["day", "night"] | None
    weather: Literal["clear", "cloudy", "rain", "snow", "fog"] | None
    day_time_evidence: list[Evidence]
    weather_evidence: list[Evidence]

    @model_validator(mode="after")
    def require_evidence(self):
        for name in ("day_time", "weather"):
            if getattr(self, name) is not None and not getattr(self, f"{name}_evidence"):
                raise ValueError("scene_condition_requires_evidence")
        return self


class InvolvedObject(StrictModel):
    type: Literal["Pedestrian", "Car", "Truck", "Bus", "Motorcycle", "Bicycle", "Dynamic"]
    count: int = Field(ge=1, strict=True)
    evidence: list[Evidence] = Field(min_length=1)


class SceneFacts(StrictModel):
    schema_version: Literal["scene-facts-v2"] = Field(
        description="반드시 scene-facts-v2 고정값. v2.0 등 다른 버전 표기 금지", json_schema_extra=_singleton_enum)
    description: str = Field(min_length=1)
    accident_presence: VisualFact
    accident_type: Literal["rear-end", "head-on", "sideswipe", "t-bone", "single"] | None
    accident_type_evidence: list[Evidence]
    scene_conditions: SceneConditions
    involved_objects: list[InvolvedObject]
    features: Features
    uncertainties: list[str]

    @model_validator(mode="after")
    def require_accident_evidence(self):
        if self.accident_type is not None:
            if self.accident_presence.state != "present" or not self.accident_type_evidence:
                raise ValueError("accident_type_requires_confirmed_collision_evidence")
        return self


def media_context(event, media):
    """Assign IDs to ordered binary parts; never guess missing timeline offsets."""
    evidence = event.get("evidence") or {}
    frames = {frame["asset_id"]: frame for frame in evidence.get("frames", [])}
    result = []
    for index, (asset_id, mime, _) in enumerate(media, start=1):
        is_clip = asset_id == evidence.get("clip_asset_id") and mime.startswith("video/")
        result.append({"asset_id": asset_id, "part_index": index, "mime_type": mime,
            "kind": "clip" if mime.startswith("video/") else "frame",
            "clip_start_seconds": evidence.get("clip_start_seconds") if is_clip else None,
            "clip_end_seconds": evidence.get("clip_end_seconds") if is_clip else None,
            "source_time_seconds": frames.get(asset_id, {}).get("source_time_seconds")})
    return result


def validate_provenance(facts: SceneFacts, context: dict):
    """Validate supplied asset identities and all available time mappings."""
    assets = {item["asset_id"]: item for item in context["media"]}
    def walk(value):
        if isinstance(value, dict):
            if "asset_id" in value:
                asset = assets.get(value["asset_id"])
                if asset is None:
                    raise ValueError("invalid_evidence_asset_id")
                clip, source = value["clip_time_seconds"], value["source_time_seconds"]
                if any(t is not None and not math.isfinite(t) for t in (clip, source)):
                    raise ValueError("invalid_evidence_time")
                if asset["kind"] == "frame":
                    if clip is not None:
                        raise ValueError("frame_has_no_clip_time")
                    expected = asset["source_time_seconds"]
                    if source is not None and (expected is None or abs(source - expected) > .05):
                        raise ValueError("invalid_frame_source_time")
                else:
                    start, end = asset["clip_start_seconds"], asset["clip_end_seconds"]
                    if clip is not None and (start is None or end is None or clip > end - start + .05):
                        raise ValueError("invalid_clip_time")
                    if source is not None and (start is None or end is None or not start <= source <= end):
                        raise ValueError("invalid_clip_source_time")
                    if clip is not None and source is not None and abs(start + clip - source) > .05:
                        raise ValueError("inconsistent_evidence_time_mapping")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(facts.model_dump())
    if any(item.type == "Dynamic" for item in facts.involved_objects):
        def has_dynamic(value):
            if isinstance(value, dict):
                return any(v == "Dynamic" for v in value.values() if isinstance(v, str)) or any(has_dynamic(v) for v in value.values())
            return isinstance(value, list) and any(has_dynamic(v) for v in value)
        if not has_dynamic(context["detector_observations"]):
            raise ValueError("dynamic_requires_detector_evidence")


def to_rag_input(facts: SceneFacts, event):
    def boolean(fact):
        return {"present": True, "absent": False, "unknown": None}[fact.state]
    return {"schema_version": facts.schema_version, "event_id": event["event_id"],
        "candidate_time_s": event.get("candidate_time_s"), "description": facts.description,
        "scene_conditions": facts.scene_conditions.model_dump(),
        "involved_objects": [item.model_dump() for item in facts.involved_objects],
        "accident_type": facts.accident_type, "accident_presence": facts.accident_presence.model_dump(),
        "features": facts.features.model_dump(), "uncertainties": facts.uncertainties,
        # Compatibility aliases for stored report/UI consumers; this is VLM assessment, not human approval.
        "operator_confirmed": boolean(facts.accident_presence),
        "lane_blocked": boolean(facts.features.lane_blockage),
        "affected_person_visible": boolean(facts.features.affected_people_visible),
        "fire_visible": boolean(facts.features.flames)}
