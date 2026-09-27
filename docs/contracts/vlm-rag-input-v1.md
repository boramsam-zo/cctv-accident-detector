# VLM → RAG 장면 입력 계약 v1

사고 의심 후보의 실제 clip·대표 frame을 Gemini가 분석하면 백엔드는 후보의 `rag_input`에 다음 JSON을 저장한다. RAG 검색 구현은 이 객체를 입력으로 사용한다. 현재 RAG 검색기는 아직 연결되지 않았다.

```json
{
  "event_id": "event_000",
  "candidate_time_s": 12.5,
  "description": "차량 두 대가 가까워집니다. 접촉 여부는 이 장면만으로 확인되지 않습니다.",
  "scene_conditions": {"day_time": "day", "weather": null},
  "involved_objects": [{"type": "car", "count": 2}],
  "accident_type": null,
  "lane_blocked": null,
  "affected_person_visible": false,
  "fire_visible": false,
  "operator_confirmed": null
}
```

위 JSON은 형식 예시이며 실제 영상 판정 결과가 아니다.

| 필드 | 생성 주체·규칙 |
| --- | --- |
| `event_id` | 백엔드가 등록한 이벤트 ID. Gemini가 생성하지 않음 |
| `candidate_time_s` | Runpod이 반환한 후보 시각(원본 시작 기준 초). event 등록 시 manifest와 요청 본문의 값이 일치해야 함. 단독 presigned URL 미리보기에서만 미제공 시 `null` |
| `description` | Gemini가 실제 clip·frame을 근거로 작성한 한국어 요약 |
| `scene_conditions.day_time` | `day`, `night`, `twilight` 또는 판단 불가 시 `null` |
| `scene_conditions.weather` | 화면에서 직접 확인 가능한 기상만 기록. 불명확하면 `null` |
| `involved_objects[].type/count` | 관련 객체의 관찰 가능한 종류와 수. 확인되지 않으면 빈 배열 |
| `accident_type` | 추돌·측면충돌·차량 전도 등 형태가 확인될 때만 문자열, 아니면 `null` |
| `lane_blocked`, `affected_person_visible`, `fire_visible` | 보이면 `true`, 관찰 가능하고 없으면 `false`, 판단 불가 시 `null` |
| `operator_confirmed` | Gemini가 X3D-S 후보를 영상으로 재확인한 값. 사고 장면이 보이면 `true`, 정상 장면이 명확하면 `false`, 판단 불가 시 `null`. 사람 검토와 별개 |

Gemini 구조화 출력은 `services/backend/gemini_vlm.py`의 Pydantic 스키마로 검증한다. 기존 후보 결과의 `vlm.observations`와 근거 asset ID 검증을 유지한다. VLM 실패 시 `rag_input`은 만들지 않는다. 사람 검토 결과는 별도 `human_review`에 기록하고 `operator_confirmed`를 덮어쓰지 않는다. 이 객체의 영상 관찰값은 법적 사실 확정이 아니며, RAG는 확인되지 않은 값을 검색 필터로 강제하지 않는다.
