import pytest


@pytest.fixture
def scene_payload():
    """Synthetic contract fixture, not human-reviewed clip ground truth."""
    def make(asset_id="frame-1", *, accident="unknown", flames="unknown", lane="unknown"):
        ref = {"asset_id": asset_id, "clip_time_seconds": None, "source_time_seconds": None}
        def fact(state):
            return {"state": state, "reason": "테스트 관찰" if state != "unknown" else "판단 불가",
                    "evidence": [dict(ref)] if state != "unknown" else []}
        return {"schema_version": "scene-facts-v2", "description": "테스트 장면",
            "accident_presence": fact(accident), "accident_type": None, "accident_type_evidence": [],
            "scene_conditions": {"day_time": None, "weather": None, "day_time_evidence": [], "weather_evidence": []},
            "involved_objects": [], "features": {name: fact(state) for name, state in (
                ("mountain_road", "unknown"), ("visible_vegetation_near_fire", "unknown"),
                ("flames", flames), ("smoke", "unknown"), ("debris", "unknown"),
                ("lane_blockage", lane), ("affected_people_visible", "unknown"),
                ("visible_forest_burning", "unknown"))}, "uncertainties": ["부상 미확인"]}
    return make
