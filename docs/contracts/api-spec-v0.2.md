# CCTV 사고 의심 분석 API 명세서 — v0.2

> 공개 `/api/v1` 계약과 Modal GPU 함수 연결을 구분합니다. 함수 입력·S3 결과 계약은 [Modal 추론 연결 계약](modal-inference-v1.md)을 따릅니다.

작성일: 2026-09-27

2026-10-04 확장: `/api/v1/vlm-options`의 기본 프롬프트 ID는 `scene-facts-v2`입니다.
완료 후보의 `vlm.raw_output`, `vlm.request.input`, `vlm.validation`, `rag_input.features`에는
[VLM 영상 관찰 계약](../VLM_FACTS_VALIDATION.md)이 적용됩니다. 기존 결과 JSON도 계속 조회할 수 있습니다.

상태: 공개 API·Modal·S3·Gemini·RAG 연결 구현 및 실제 서비스 E2E 확인. 검증 범위는 [진행 기록](../PROGRESS.md) 참고.
기준: [PRD](../../PROJECT_BRIEF.md) · [공통 서비스 계약](service_contract.md) · [가상 응답](demo-analysis-cases-v0.2.json)

이 문서는 Streamlit과 FastAPI 사이의 HTTP 계약을 정의한다. BE 작업 프로세스의 Modal 제출·S3 결과 회수는
[Modal 추론 연결 계약](modal-inference-v1.md)을 따른다.

## 1. 기본 규칙

| 항목 | 규칙 |
|---|---|
| Base path | `/api/v1` |
| 요청/응답 형식 | JSON. 단, 영상 등록은 `multipart/form-data` |
| 문자 인코딩 | UTF-8 |
| 서버 시각 | UTC ISO 8601 (`2026-09-27T04:30:00Z`) |
| 영상 시각 | 원본 영상 시작을 `0.0`으로 한 초 단위 실수 |
| 인증 | 모든 API에 필요. 방식과 권한 모델은 TBD |
| 요청 추적 | 서버는 모든 응답에 `X-Request-ID`를 반환 |
| 멱등성 | 생성 API는 `Idempotency-Key` 헤더 필수 |
| 스키마 버전 | 결과 본문 `schema_version = service-draft-v0.2` |

`Idempotency-Key`는 요청자와 endpoint 범위에서 유일해야 한다. 같은 키와 같은 요청 본문은 최초
응답을 반환하고, 같은 키에 다른 내용이 오면 `409 IDEMPOTENCY_KEY_REUSED`를 반환한다. 보존 기간은
job 보존 기간 이상으로 한다.

## 2. API 목록

| 영역 | 메서드 | 경로 | 설명 |
|---|---|---|---|
| 영상 | POST | `/videos` | 영상 검증·저장·등록 |
| 영상 | GET | `/videos` | 등록 영상 목록 조회 |
| 프로필 | GET | `/analysis-profiles` | 사용 가능한 분석 프로필 조회(제안) |
| 작업 | POST | `/jobs` | 영상 분석 작업 생성 |
| 작업 | GET | `/jobs` | 작업 목록 조회 |
| 작업 | GET | `/jobs/{job_id}` | 작업과 특정 run 결과 조회 |
| 작업 | POST | `/jobs/{job_id}/runs` | 기존 영상 재분석 |
| 자산 | GET | `/assets/{asset_id}/url` | 접근 확인 후 단기 URL 발급 |
| 검토 | POST | `/events/{event_id}/reviews` | 사람 검토 이력 추가 |
| 검토 | GET | `/events/{event_id}/reviews` | 사람 검토 이력 조회 |

`GET /analysis-profiles`는 FE가 임의의 profile ID를 입력하지 않게 하기 위한 추가 제안이다. 프로필을
서버 설정으로 하나만 고정한다면 이 API를 제외하고 FE에 고정 ID를 배포할 수 있다.

## 3. 공통 형식

### 3.1 페이지 응답

```json
{
  "items": [],
  "next_cursor": null
}
```

- `limit`: 기본값과 최대값 TBD. 양의 정수만 허용한다.
- `cursor`: 서버가 발급한 불투명 문자열이다. 클라이언트가 내용을 해석하거나 생성하지 않는다.
- `next_cursor`: 다음 페이지가 없으면 `null`이다.
- 목록의 기본 정렬은 `created_at DESC, id DESC`로 제안한다.

### 3.2 오류 응답

```json
{
  "error": {
    "code": "VIDEO_FORMAT_UNSUPPORTED",
    "message": "지원하지 않는 영상 형식입니다.",
    "retryable": false,
    "details": null
  },
  "request_id": "req_01..."
}
```

`message`는 사용자 표시가 가능하되 내부 경로, stack trace, S3 key, 자격증명을 포함하지 않는다.
필드별 입력 오류가 있을 때만 `details`에 아래 형식을 사용한다.

```json
{
  "fields": [
    {"field": "analysis_profile_id", "reason": "unknown_profile"}
  ]
}
```

| HTTP | 대표 코드 | 의미 |
|---|---|---|
| 400 | `INVALID_REQUEST` | 요청 형식 또는 쿼리 조합 오류 |
| 401 | `AUTHENTICATION_REQUIRED` | 인증되지 않음 |
| 403 | `ACCESS_DENIED` | 해당 자원 접근 권한 없음 |
| 404 | `RESOURCE_NOT_FOUND` | 자원이 없거나 비공개 정책상 숨김 |
| 409 | `IDEMPOTENCY_KEY_REUSED`, `RUN_ALREADY_ACTIVE`, `REVIEW_REVISION_CONFLICT` | 현재 상태와 충돌 |
| 413 | `VIDEO_TOO_LARGE` | 허용 파일 크기 초과 |
| 415 | `VIDEO_FORMAT_UNSUPPORTED` | 지원하지 않는 미디어 형식 |
| 422 | `VIDEO_INVALID`, `PROFILE_NOT_FOUND`, `VALIDATION_FAILED` | 내용 또는 계약 검증 실패 |
| 429 | `RATE_LIMITED` | 요청 또는 사용량 제한 초과 |
| 503 | `SERVICE_UNAVAILABLE` | 일시적 외부/내부 서비스 장애 |

인증된 사용자에게도 다른 사용자의 자원 존재 여부를 숨겨야 한다면 403 대신 404를 일관되게 사용한다.
이 정책은 인증 방식과 함께 확정한다.

## 4. 영상 API

### 4.1 영상 등록

`POST /api/v1/videos`

필수 헤더:

```http
Idempotency-Key: <opaque-client-generated-key>
Content-Type: multipart/form-data
```

| form 필드 | 형식 | 필수 | 설명 |
|---|---|---:|---|
| `file` | binary | O | 원본 영상. 허용 확장자·MIME·크기·길이 TBD |
| `camera_id` | string | X | 알려진 카메라 식별자 |
| `recorded_at` | UTC ISO 8601 | X | 알려진 촬영 시작 시각 |

성공: `201 Created`

```json
{
  "source_video_id": "vid_01...",
  "upload_status": "ready",
  "file_name": "camera-01.mp4",
  "content_type": "video/mp4",
  "size_bytes": 10485760,
  "sha256": "<64 lowercase hex>",
  "duration_seconds": 30.5,
  "camera_id": "camera-01",
  "recorded_at": "2026-09-27T01:00:00Z",
  "created_at": "2026-09-27T04:30:00Z"
}
```

서버가 파일 검증과 S3 저장을 완료한 후에만 `ready`를 반환한다. 실패한 업로드에 대해 video/job을
정상 생성하지 않는다. 파일명은 표시용이며 모델 판정 입력이나 접근 권한 판단에 사용하지 않는다.

### 4.2 영상 목록

`GET /api/v1/videos?cursor={cursor}&limit={limit}`

성공: `200 OK`

```json
{
  "items": [
    {
      "source_video_id": "vid_01...",
      "file_name": "camera-01.mp4",
      "content_type": "video/mp4",
      "size_bytes": 10485760,
      "duration_seconds": 30.5,
      "camera_id": "camera-01",
      "recorded_at": "2026-09-27T01:00:00Z",
      "created_at": "2026-09-27T04:30:00Z"
    }
  ],
  "next_cursor": null
}
```

## 5. 분석 프로필 API

### 5.1 프로필 목록

`GET /api/v1/analysis-profiles`

성공: `200 OK`

```json
{
  "items": [
    {
      "analysis_profile_id": "profile_default_v1",
      "display_name": "기본 사고 의심 분석",
      "description": "X3D-S 후보 탐색 후 YOLO11s 객체 정보를 추가합니다.",
      "is_default": true,
      "enabled": true
    }
  ]
}
```

응답은 사용자가 선택 가능한 공개 정보만 포함한다. 가중치 S3 경로, 비밀 값, 내부 배포 설정은 노출하지 않는다.

## 6. 작업 API

### 6.1 분석 작업 생성

`POST /api/v1/jobs`

필수 헤더: `Idempotency-Key`

```json
{
  "source_video_id": "vid_01...",
  "analysis_profile_id": "profile_default_v1"
}
```

성공: `202 Accepted`

```json
{
  "job_id": "job_01...",
  "run_id": "run_01...",
  "status": "queued",
  "detection_outcome": "pending",
  "created_at": "2026-09-27T04:31:00Z"
}
```

DB에 job과 최초 run이 커밋된 뒤 응답한다. 별도 BE 작업 프로세스가 Modal 함수를 비동기 제출하며 GPU 완료를 HTTP 요청에서 기다리지 않는다.

### 6.2 작업 목록

`GET /api/v1/jobs`

지원 쿼리:

| 쿼리 | 형식 | 설명 |
|---|---|---|
| `cursor` | string | 다음 페이지 커서 |
| `limit` | integer | 페이지 크기 |
| `status` | enum | 단일 작업 상태 필터(제안) |
| `source_video_id` | string | 특정 영상의 작업 필터(제안) |

성공: `200 OK`

```json
{
  "items": [
    {
      "job_id": "job_01...",
      "active_run_id": "run_01...",
      "source_video_id": "vid_01...",
      "status": "enriching",
      "detection_outcome": "candidates_found",
      "candidate_count": 1,
      "created_at": "2026-09-27T04:31:00Z",
      "updated_at": "2026-09-27T04:32:00Z"
    }
  ],
  "next_cursor": null
}
```

### 6.3 작업 상세

`GET /api/v1/jobs/{job_id}?run_id={run_id}`

- `run_id` 생략 시 `active_run_id` 결과를 반환한다.
- `run_id` 지정 시 반드시 해당 `job_id` 소속인지 확인한다.
- 처리 중에도 현재까지 저장된 후보·단계 상태·오류를 반환한다.

성공: `200 OK`의 본문은 다음 `JobResult` 스키마를 따른다.

#### JobResult

```json
{
  "schema_version": "service-draft-v0.2",
  "is_demo": false,
  "job_id": "job_01...",
  "run_id": "run_01...",
  "source_video_id": "vid_01...",
  "status": "completed",
  "detection_outcome": "candidates_found",
  "created_at": "2026-09-27T04:31:00Z",
  "updated_at": "2026-09-27T04:35:00Z",
  "video": {
    "duration_seconds": 30.5,
    "camera_id": "camera-01",
    "recorded_at": "2026-09-27T01:00:00Z",
    "original_asset_id": "asset_original_01"
  },
  "coverage": {
    "requested_start_seconds": 0.0,
    "requested_end_seconds": 30.5,
    "scheduled_windows": 29,
    "predicted_windows": 29,
    "unclassified_windows": 0,
    "pending_windows": 0,
    "unknown_ranges": []
  },
  "models": {
    "objects": {
      "family": "YOLO11s",
      "weights_sha256": "<64 lowercase hex>",
      "preprocessing_version": "yolo-pre-v1",
      "class_map_version": "received-yolo-7-v1"
    },
    "accident": {
      "family": "X3D-S",
      "weights_sha256": "<64 lowercase hex>",
      "preprocessing_version": "x3d-pre-v1",
      "class_map_version": "collision-binary-v1"
    },
    "candidate_policy_version": "candidate-policy-v1",
    "decision_rule_version": "decision-rule-v1"
  },
  "stages": {
    "objects": {"status": "completed", "reason_code": null},
    "accident": {"status": "completed", "reason_code": null},
    "evidence": {"status": "completed", "reason_code": null},
    "vlm": {"status": "completed", "reason_code": null},
    "rag": {"status": "insufficient_evidence", "reason_code": "no_relevant_document"},
    "report": {"status": "completed", "reason_code": null}
  },
  "candidates": [],
  "errors": []
}
```

허용 enum:

- `status`: `queued | dispatching | running | enriching | completed | partial | failed`
- `detection_outcome`: `pending | candidates_found | no_candidates | unknown`
- 단계 status: `pending | running | completed | skipped | failed`; RAG는 `insufficient_evidence` 추가
- 검토 status/decision: `unreviewed | confirmed_accident | not_accident | uncertain`

coverage는 `scheduled_windows = predicted_windows + unclassified_windows + pending_windows`를 만족해야 한다.
모든 예정 창이 정상 판정되고 후보가 0일 때만 `no_candidates`를 사용한다.

#### Candidate(Event)

```json
{
  "event_id": "evt_01...",
  "start_seconds": 12.0,
  "end_seconds": 16.0,
  "candidate_time_s": 13.0,
  "label": "suspected_accident",
  "score": 0.8,
  "score_type": "max_window_score",
  "prediction_ids": ["pred_01..."],
  "evidence": {
    "clip_asset_id": "asset_clip_01",
    "clip_start_seconds": 10.0,
    "clip_end_seconds": 18.0,
    "frames": [
      {"asset_id": "asset_frame_01", "source_time_seconds": 14.0}
    ]
  },
  "object_observations": [
    {
      "source_time_seconds": 14.0,
      "class_id": 1,
      "class_name": "Car",
      "score": 0.91,
      "bbox": [0.1, 0.2, 0.5, 0.8],
      "bbox_format": "xyxy_normalized_original"
    }
  ],
  "vlm": {
    "status": "completed",
    "summary": "두 차량의 이동 경로가 겹치는 장면이 관찰됩니다.",
    "observations": [
      {
        "text": "차량 두 대가 근접해 있습니다.",
        "evidence_asset_ids": ["asset_frame_01"],
        "source_times_seconds": [14.0]
      }
    ],
    "uncertainties": ["단일 시점만으로 충돌 여부를 확정할 수 없습니다."],
    "provider_model": "<configured-provider-model>",
    "prompt_version": "vlm-prompt-v1"
  },
  "retrieval": {
    "status": "insufficient_evidence",
    "query": "차량 근접 및 충돌 검토 지침",
    "corpus_version": "corpus-v1",
    "retrieval_version": "retrieval-v1",
    "citations": []
  },
  "report": {
    "report_id": "report_01...",
    "revision": 1,
    "status": "completed",
    "text": "사고 의심 구간 검토 초안",
    "source_event_id": "evt_01...",
    "evidence_asset_ids": ["asset_clip_01", "asset_frame_01"],
    "citation_document_ids": [],
    "limitations": ["관련 문서 근거가 충분하지 않습니다."],
    "generated_at": "2026-09-27T04:35:00Z"
  },
  "human_review": {
    "status": "unreviewed",
    "review_id": null,
    "review_revision": 0,
    "report_revision": null,
    "note": null
  }
}
```

객체 클래스는 수신 체크포인트의 `0 Pedestrian, 1 Car, 2 Truck, 3 Bus, 4 Motorcycle,
5 Bicycle, 6 Dynamic`을 보존한다. `Dynamic` 의미가 확정되기 전에는 삭제하거나 다른 클래스에 합치지 않는다.
`score`는 보정된 사고 확률로 표시하지 않는다.

### 6.4 재분석

`POST /api/v1/jobs/{job_id}/runs`

필수 헤더: `Idempotency-Key`

```json
{
  "analysis_profile_id": "profile_default_v1"
}
```

성공: `202 Accepted`

```json
{
  "job_id": "job_01...",
  "run_id": "run_02...",
  "status": "queued",
  "detection_outcome": "pending",
  "created_at": "2026-09-27T05:00:00Z"
}
```

진행 중인 active run이 있으면 `409 RUN_ALREADY_ACTIVE`를 반환한다. 새 run은 이전 결과·보고·검토를
덮어쓰지 않는다. 늦게 도착한 이전 run 결과도 active run을 변경할 수 없다.

## 7. 자산 API

### 7.1 단기 접근 URL 발급

`GET /api/v1/assets/{asset_id}/url`

성공: `200 OK`

```json
{
  "asset_id": "asset_clip_01",
  "url": "https://<short-lived-signed-url>",
  "expires_at": "2026-09-27T05:10:00Z",
  "content_type": "video/mp4"
}
```

서버는 요청자가 해당 job/run/asset에 접근 가능한지 확인한 뒤 URL을 발급한다. URL은 응답·로그·DB에
영구 식별자로 저장하지 않는다. 만료시간은 TBD다.

## 8. 사람 검토 API

### 8.1 검토 저장

`POST /api/v1/events/{event_id}/reviews`

필수 헤더: `Idempotency-Key`

```json
{
  "run_id": "run_01...",
  "report_revision": 1,
  "decision": "uncertain",
  "note": "원본의 다음 구간을 추가 확인해야 합니다.",
  "expected_review_revision": 0
}
```

| 필드 | 형식 | 필수 | 규칙 |
|---|---|---:|---|
| `run_id` | string | O | event가 속한 run과 일치해야 함 |
| `report_revision` | integer/null | O | 보고가 없으면 `null` |
| `decision` | enum | O | `confirmed_accident`, `not_accident`, `uncertain` |
| `note` | string/null | O | 최대 길이 TBD. 빈 문자열은 `null`로 정규화 제안 |
| `expected_review_revision` | integer | O | 현재 최신 revision과 일치해야 함 |

성공: `201 Created`

```json
{
  "review_id": "review_01...",
  "event_id": "evt_01...",
  "run_id": "run_01...",
  "report_revision": 1,
  "decision": "uncertain",
  "note": "원본의 다음 구간을 추가 확인해야 합니다.",
  "review_revision": 1,
  "reviewed_at": "2026-09-27T05:05:00Z"
}
```

현재 revision이 다르면 `409 REVIEW_REVISION_CONFLICT`와 최신 revision을 반환한다. 검토자 ID는 요청
본문이 아니라 인증 문맥에서 기록한다. 새 검토는 이력을 추가하며 기존 행을 덮어쓰지 않는다.

### 8.2 검토 이력

`GET /api/v1/events/{event_id}/reviews?cursor={cursor}&limit={limit}`

성공: `200 OK`

```json
{
  "items": [
    {
      "review_id": "review_01...",
      "event_id": "evt_01...",
      "run_id": "run_01...",
      "report_revision": 1,
      "decision": "uncertain",
      "note": "원본의 다음 구간을 추가 확인해야 합니다.",
      "review_revision": 1,
      "reviewed_at": "2026-09-27T05:05:00Z"
    }
  ],
  "next_cursor": null
}
```

검토자 표시명 또는 식별자 노출 여부는 인증·개인정보 정책 확정 후 추가한다.

## 9. 상태별 클라이언트 처리

| 조건 | FE 표시·동작 |
|---|---|
| `queued/dispatching/running` | 분석 중. 근거 없는 진행률·완료 예상시간 표시 금지 |
| `enriching` | 후보와 실제 장면을 먼저 표시하고 설명 준비 중 표시 |
| `completed + no_candidates` | “분석된 범위에서 사고 의심 후보 없음” |
| `partial + unknown` | 미분류/미처리 범위와 오류 표시. 사고 없음으로 표시 금지 |
| `failed` | 실패 단계·재시도 가능 여부 표시, 과거 run 보존 |
| RAG `insufficient_evidence` | 검색 장애가 아닌 문서 근거 부족으로 표시 |
| URL 만료 | 자산 URL API를 다시 호출 |
| 검토 409 | 최신 검토 이력을 다시 읽고 사용자가 재확인 |

Streamlit은 terminal 상태(`completed`, `partial`, `failed`)에서 자동 조회를 멈춘다. 새로고침이나 버튼
중복 클릭 시 같은 사용자 동작에는 같은 `Idempotency-Key`를 재사용한다.

## 10. Modal GPU 함수 연결

Modal 호출은 Streamlit이 사용하는 HTTP API가 아니다. BE 작업 프로세스가 queued run을 `spawn()`으로 제출하고 `modal_call_id`를 DB에 저장한다. 완료는 같은 프로세스가 호출 ID로 조회한다. 함수는 업로드 원본과 가중치를 S3에서 읽고 event/final manifest 및 clip·frame을 S3에 저장한다. BE는 결과 경로·SHA256·시각·coverage를 검증한 후 `GET /jobs/{job_id}` 응답에 후보와 상태를 반영한다. 함수 입력·출력과 실패 규칙은 [Modal 추론 연결 계약](modal-inference-v1.md)에 정의한다.

## 11. 확정이 필요한 항목

아래 항목은 API 구현 전에 제품·인프라·모델 담당자가 결정해야 한다.

| 우선순위 | 결정 항목 | API 영향 |
|---|---|---|
| P0 | 인증 방식과 사용자/역할/자원 접근 범위 | 모든 API의 401/403/404, 검토자 기록 |
| P0 | 허용 영상 MIME/코덱, 최대 파일 크기·길이 | POST `/videos`, 413/415/422 |
| P0 | 실제 `analysis_profile_id`와 X3D 창·간격·임계값·후처리 | POST `/jobs`, 결과 재현성 |
| P0 | `Dynamic` 클래스의 뜻과 UI 표시명 | Candidate 객체 정보 표시 |
| P0 | 후보 병합, 근거 클립 전후 길이, 대표 프레임 정책 | event/evidence 필드 |
| P0 | 목록 기본/최대 `limit` 및 보존 기간 | 목록 API, 멱등 키·데이터 보존 |
| P0 | signed URL 만료시간과 다운로드/스트리밍 정책 | 자산 API와 영상 재생 |
| P0 | Modal GPU 종류·리전·image·timeout·동시 실행 상한 | 처리시간·가용성·비용 |
| P0 | 원본 영상 시각과 후보 clip·frame 시각의 허용 오차 | 근거 정합성 |
| P0 | Modal call ID 저장 실패·프로세스 재시작·결과 회수 정책 | 장애 복구·중복 처리 |
| P0 | VLM 제공자와 개인정보·원본 전송 허용 범위 | VLM 상태·오류·감사 기록 |
| P0 | RAG corpus 종류·적용 지역·출처 공개 범위 | citation 스키마와 화면 표시 |
| P1 | rate limit·동시 job·사용량 상한 | 429와 재시도 안내 |
| P1 | 검토 메모 최대 길이와 검토자 정보 노출 | 검토 API 검증·응답 |
| P1 | 영상·결과·검토 보관/삭제 정책 | 삭제 API 필요 여부와 접근 정책 |

삭제 API, 작업 취소 API, 단계별 수동 재시도 API는 정책과 운영 요구가 확정되지 않아 v0.2 외부 API에
포함하지 않았다. 첫 버전의 사용자 재시도는 새 run 생성으로 제한한다.

## 12. 구현·검증 기준

- FastAPI 구현 시 이 문서와 동일한 OpenAPI schema를 생성하고 FE가 해당 schema로 연동한다.
- 공개 API 계약 테스트와 실제 업로드→Modal→S3 결과→Gemini JSON E2E를 각각 확인한다.
- 같은 멱등 키의 중복 요청, 다른 본문의 키 재사용, 진행 중 재분석, 검토 revision 충돌을 시험한다.
- 실패·미분류를 `no_candidates`로 변환하지 않는지 확인한다.
- 다른 사용자 asset 접근과 만료 URL을 확인한다.
- 실제 업로드 영상/S3/Modal/모델/Gemini 연결 시험은 단위·계약 시험과 별도로 기록한다.
