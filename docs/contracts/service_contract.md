# 공통 API·데이터 계약 — service-draft-v0.2

> GPU 작업은 [Modal 추론 연결 계약](modal-inference-v1.md)을 따릅니다. 이 문서는 공개 API·결과 데이터·사람 검토 계약을 함께 정의합니다.

작성일 2026-09-26. **개발 계약이며 공개 API와 Modal 연결은 일부 구현됐다. 실제 GPU 통합은 검증 전이다.** PRD의 기능 범위를 FE·BE·모델·VLM/RAG가 같은 이름으로 연결하기 위한 기준이다. 실제 저장소에 존재하는 R3D 결과 JSON과 자동 호환된다고 가정하지 않는다.

공통 필드·상태·API 변경은 이 문서에서 먼저 한다. 역할별 문서는 이를 링크한다. 예시는 [가상 응답 모음](demo-analysis-cases-v0.2.json)이며 실제 영상·예측·문서 인용을 포함하지 않는다.

## 1. 식별자와 저장 책임

| 항목 | 정의·책임 |
|---|---|
| `source_video_id` | BE가 등록한 원본 영상 ID. 파일 이름은 표시용이며 모델 입력에 사고 암시 정보로 전달하지 않음 |
| `job_id` | 사용자의 한 분석 요청. 원본·분석 범위·요청자·선택한 설정 버전 연결 |
| `run_id` | 실제 처리 시도. 재분석은 새 ID. 이전 run의 결과·실패·검토는 보존 |
| `modal_call_id` | Modal `spawn()`으로 받은 비동기 함수 호출 ID. `runs`에 보관하고 결과 회수에 사용 |
| `event_id` | run 안에서 생성한 검토 후보 ID. 실제 사고 사건의 확정 ID가 아님 |
| `asset_id` | 원본·클립·프레임·manifest 등 파일의 ID. DB가 bucket/key/version/checksum과 연결 |
| `report_id`, `revision` | 후보에 연결된 보고 초안과 버전. 후속 단계 재시도로 새 버전 생성 |
| `review_id` | 사람이 특정 event/run/report revision을 보고 남긴 판단 기록 |

모든 서버 시각은 UTC ISO 8601, 영상 시각은 원본 시작 기준 초(double)다. `recorded_at`과 `camera_id`는 알 때만 채운다. 실행 경과시간, 영상 상대시각, 실제 촬영 시계를 혼합하지 않는다.

## 2. 작업 상태와 판정 분리

`status`: `queued`, `dispatching`, `running`, `enriching`, `completed`, `partial`, `failed`.

| 상태 | 정의 |
|---|---|
| queued | 요청·run이 DB에 저장되어 처리 대기 |
| dispatching | BE 작업 프로세스가 Modal 함수를 제출 중. 호출 ID 저장 전 오류는 실패로 기록 |
| running | Modal 함수 호출 ID가 저장됐고 GPU 결과를 기다리거나 회수 중 |
| enriching | 후보·영상 근거가 등록됐고 설명·검색·보고를 처리 중 |
| completed | 요청 범위 처리·필요 단계가 끝남. 후보 없음, RAG 근거 부족도 정상 종료일 수 있음 |
| partial | 사용할 결과가 있으나 미분류/미처리 또는 필수 단계 실패가 남음 |
| failed | 사용할 모델 판정·근거가 없거나 안전하게 결과를 등록할 수 없음 |

기본 전이: queued→dispatching→running→enriching→completed/partial. 후보 0이면 enriching을 생략할 수 있다. 처리 중 실패 시 usable 결과가 있으면 partial, 없으면 failed다. terminal 상태의 재분석은 새 run으로 queued부터 시작한다.

`detection_outcome`: `pending`, `candidates_found`, `no_candidates`, `unknown`. `no_candidates`는 예정된 모든 창의 유효 판정이 있고 후보가 0일 때만 사용한다. 후보 0이라도 미분류/미처리가 있으면 unknown이다. 모델이 판정한 결과이며 실제 사고 부재를 확정하지 않는다.

단계 키: `objects`, `accident`, `evidence`, `vlm`, `rag`, `report`. 각 값은 `{status, reason_code}`이며 단계 상태는 `pending/running/completed/skipped/failed`; RAG만 `insufficient_evidence` 추가 허용. 이유 없는 skipped는 금지한다.

- 후보 0: objects/VLM/RAG/report를 `skipped/no_candidates`로 종료. 작업 요약은 계속 제공한다.
- 판정 불가: VLM/RAG/report `skipped/no_usable_candidate`이며 사고 없음으로 표시하지 않는다.
- VLM 실패: 후보는 유지, RAG `skipped/vlm_unavailable`, 보고는 실패 사실과 영상 근거만으로 조립; 작업 partial.
- RAG 근거 부족: 오류와 구분해 `insufficient_evidence`와 빈 인용, 보고에 근거 부족 표시; 다른 결함이 없다면 completed.
- RAG 연결 실패 또는 보고 실패: partial, 단계 오류 표시. UI는 기존 근거를 계속 보여준다.

사람 검토 상태는 `unreviewed/confirmed_accident/not_accident/uncertain`이며 job 상태와 독립이다. AI 완료를 사람 검토 완료로 바꾸지 않는다. 후보별 상태가 여러 개면 job의 단계 상태는 failed 우선, 다음 running, pending, insufficient_evidence, completed 순으로 집계하되 전부 skipped이면 skipped다. 원인 상세는 event에 남긴다.

## 3. API 초안

요청·응답 예시, 오류 코드, 페이지네이션, 클라이언트 처리 규칙은
[HTTP API 상세 명세](api-spec-v0.2.md)를 따른다. 이 절은 서비스 경계와 핵심 규칙의 요약이다.

기본 경로 `/api/v1`. 모든 요청은 팀 서비스의 접근 통제 대상이다. UI에서는 DB/S3/Modal 장기 자격증명을 직접 쓰지 않는다. 초기 Streamlit 서버가 API로 파일을 전송하는 방식을 제안한다. 대용량 직업로드가 필요해지면 별도 업로드 계약을 버전 관리한다.

| 메서드·경로 | 요청 | 응답·기준 |
|---|---|---|
| POST /videos | multipart `file`; 선택 `camera_id`, `recorded_at`; `Idempotency-Key` | 201 `{source_video_id, upload_status: ready}`. API가 파일 검증·S3 저장을 마친 후 반환; 저장 실패 시 job 생성 안 함 |
| GET /videos | `cursor`, `limit` | 200 `{items, next_cursor}`. 허용된 원본만 조회 |
| POST /jobs | JSON `{source_video_id, analysis_profile_id}`; `Idempotency-Key` | 202 `{job_id, run_id, status: queued}`. DB 커밋 후 반환, GPU 완료를 기다리지 않음 |
| GET /jobs | `cursor`, `limit` | 200 `{items, next_cursor}`. ID·원본·상태·생성시각·후보 수 |
| GET /jobs/{job_id} | 선택 `run_id` | 200 JobResult. 생략하면 active run. 존재하지 않거나 접근 불가한 ID 구분 정책은 BE에서 일관되게 적용 |
| POST /jobs/{job_id}/runs | `{analysis_profile_id}`; `Idempotency-Key` | 202 새 run. 실행 중 중복 재분석은 409. 이전 run·검토 유지 |
| GET /assets/{asset_id}/url | 없음 | 200 `{url, expires_at}`. 접근 확인 후 단기 URL 발급. DB에는 URL을 영구 보관하지 않음 |
| POST /events/{event_id}/reviews | `{run_id, report_revision, decision, note, expected_review_revision}`; `Idempotency-Key` | 201 `{review_id, review_revision, reviewed_at}`. 검토자 식별은 서버 인증 문맥으로 기록; 초안이 없으면 report_revision=null |
| GET /events/{event_id}/reviews | 없음 | 200 `{items}`. 새 검토는 이력을 추가, 기존 행 덮어쓰기 금지 |

동일 Idempotency-Key+동일 내용은 최초 응답을 반환한다. 같은 키에 다른 내용은 409. 키의 범위는 요청자+endpoint, 보존 기간은 job 보존 기간 이상으로 제안한다. API 오류 형식은 `{error: {code, message, retryable}, request_id}`다. 413 크기 초과, 415 형식 미지원, 422 입력·계약 위반, 409 상태/버전 충돌, 503 서비스 일시 불가를 구분한다.

검토 저장 시 expected_review_revision이 현재값과 다르면 409 후 새 기록을 다시 확인하게 한다. 예전 report_revision에 대한 검토는 보존하고 최신 초안에서는 ‘이전 버전 검토’로 표시한다. 별도 검토자 입력만 있는 시연은 인증된 신원으로 표시하지 않는다.

## 4. Modal GPU 함수 입력·결과 회수

백엔드 작업 프로세스는 DB의 queued run을 찾아 `dispatching`으로 바꾸고 Modal `analyze_video_job`에 `spawn()`으로 제출한다. 반환된 `modal_call_id`를 `runs`에 저장한 뒤 `running`으로 바꾼다. 주기적으로 `FunctionCall.from_id(call_id).get(timeout=0)`으로 완료를 확인한다. 공개 API 요청은 GPU 완료를 기다리지 않는다.

입력은 `schema_version=modal-inference-v1`, `job_id`, `run_id`, `source_video_id`, `input_object={bucket,key,sha256}`, `output_prefix`, `attempt`, `analysis_profile={id,analysis_mode=offline_video}`, `duration_seconds`다. 업로드 원본만 입력으로 사용하고, 가중치 버킷·객체 키·SHA256은 Modal `cctv-s3` Secret에서 읽는다. 실제 CCTV/RTSP 입력과 원본 속도 1× 실시간 분석은 현재 범위 밖이다.

Modal 함수는 X3D-S로 후보를 찾고 후보 시각의 원본 한 프레임에 YOLO11s를 실행한다. clip·frame·event manifest·final manifest를 영상 버킷의 run/attempt `output_prefix`에 저장한다. 결과로 event manifest 참조 목록과 final manifest의 경로·SHA256을 반환한다. 임시 컨테이너 디스크는 영구 결과 저장소가 아니다.

BE는 반환된 모든 경로가 할당된 `output_prefix` 아래인지, S3 객체가 존재하는지, SHA256·MIME·run/event 식별자·원본 영상 시각·coverage 창 개수가 맞는지 검증한 후 DB에 등록한다. `candidate_time_s`는 X3D-S 첫 양성 창의 중간 시각이며 정확한 충돌 시각이 아니다. 후보가 없으면 VLM·RAG를 건너뛴다. Modal 호출 또는 결과 검증이 실패하면 원인 단계와 함께 `failed`로 남기며 사고 없음으로 바꾸지 않는다.

GPU 제출·결과 회수와 Gemini 후처리는 FastAPI 요청과 분리된 BE 작업 프로세스에서 실행한다. 브라우저 세션이나 Modal 호출 핸들만 영구 상태로 사용하지 않고 S3·PostgreSQL에 보존한다. 현재 호출 직후 프로세스 중단 시 call ID 복구와 장기 재시도 정책은 검증·보완이 필요하다.

## 5. 결과 데이터의 공통 필드

### JobResult

| 필드 | 형식·의미 |
|---|---|
| schema_version, is_demo | `service-draft-v0.2`, 실제 응답 false/가상 fixture true |
| job_id, run_id, source_video_id | 서로 다른 역할의 문자열 ID |
| status, detection_outcome | 2절 enum |
| video | duration_seconds, camera_id(null 허용), recorded_at(null 허용), original_asset_id |
| coverage | requested_start_seconds, requested_end_seconds, scheduled_windows, predicted_windows, unclassified_windows, pending_windows, unknown_ranges |
| models | objects/accident별 family, weights_sha256, preprocessing_version, class_map_version; candidate_policy_version·decision_rule_version |
| stages | 단계별 상태·이유 |
| candidates | Event 배열. pending/failed의 빈 배열은 정상 판정이 아님 |
| errors | `{stage, code, message, retryable}` 배열 |

`scheduled_windows = predicted_windows + unclassified_windows + pending_windows`여야 한다. 계획된 창이 0이면 no_candidates 금지. 범위 시작·끝/워밍업/영상 꼬리·미처리 부분을 unknown_ranges 또는 처리 범위 설명으로 남긴다. 전체 영상 분석을 표방하면 범위 밖 구간도 명시한다. 알 수 없는 값은 null이며 0으로 바꾸지 않는다.

### 모델별 역할

사용자 확정: X3D-S는 사고 후보 구간, YOLO는 사고 영상의 객체 정보를 제공한다. 개발 제안: X3D-S 후보 정리 후 해당 원본 장면에 YOLO를 실행해 시간 기준으로 결합한다. YOLO 출력은 X3D-S 입력이 아니다. objects 실패 시에도 X3D 후보·실제 장면을 보존하고 누락을 표시해 partial로 처리한다.

### 수신 handoff schema 1.0의 변환

수신 코드와 서비스 계약 사이 어댑터는 아직 미구현이다. 수신 파일 자체를 서비스 결과로 그대로 등록하지 않는다.

| 수신 필드 | 서비스 변환 | 주의 |
|---|---|---|
| video_id/video_filename | 등록한 source_video_id | 파일 이름으로 권한/동일성 판단 금지 |
| event_id | run 안에서 유일한 event_id | 여러 실행의 event_000 충돌 방지 |
| events.start_s/end_s | start_seconds/end_seconds | result.json의 병합 구간 사용 |
| candidate_time_s | candidate_time_s | X3D-S 후보 시각. 첫 양성 창의 중간 시각이며 정확한 충돌시각 아님 |
| available_after_video_time_s | decision_source_time_seconds | 첫 양성 창 끝, 실제 wall-clock 지연과 다름 |
| candidate_window_s | trigger_window_seconds | 첫 창 범위; 전체 후보 구간으로 대체하지 않음 |
| x3d_probability_at_trigger | trigger_score | 보정된 사고 확률로 표시하지 않음 |
| events.peak_probability | score, score_type=max_window_score | 최초 점수와 최고 점수 분리 |
| yolo_frame_time_s | 요청한 후보 프레임 시각 | 실제 디코딩한 PTS를 추가 확인해야 함 |
| yolo_objects.class_id/class_name/confidence | object_observations의 class_id/class_name/score | 7개 클래스 맵 검증 |
| box_xyxy_normalized | bbox, xyxy_normalized_original | 원본 기준 좌표 검증 |

수신 handoff에는 영상/프레임 파일이 없다. 서비스가 S3 원본에서 후보 주변 클립·프레임을 생성하고 asset_id, 실제 PTS, coverage, 모델/설정 버전과 오류 정보를 추가해야 한다. `handoff_example.json`은 가상 예시이므로 실제 모델 결과로 등록하지 않는다. 예시 모음 v0.2의 null asset/해시는 화면 상태용 허용값이며 실제 completed 결과의 검증에서는 거절한다.

### Event와 영상 근거

- `event_id`, `start_seconds`, `end_seconds`, `label=suspected_accident`, `score`, `score_type`, `prediction_ids`.
- `0 ≤ start_seconds < end_seconds ≤ duration_seconds`. 점수 집계 규칙은 candidate_policy_version에 포함한다.
- `evidence`: `clip_asset_id`, `clip_start_seconds`, `clip_end_seconds`, `frames[{asset_id, source_time_seconds}]`. 클립 시작 0초가 원본 몇 초인지 보존한다. 대표 프레임만으로 설명할 경우 입력 장면 수와 한계를 기록한다.
- `object_observations`: `source_time_seconds`, `class_id`, `class_name`, `score`, `bbox`, `bbox_format=xyxy_normalized_original`. 좌표는 원본 기준 [0,1], x1<x2/y1<y2. YOLO 입력 resize/letterbox 좌표를 그대로 넘기지 않는다.
- 수신 YOLO .pt의 ID/name은 **0 Pedestrian, 1 Car, 2 Truck, 3 Bus, 4 Motorcycle, 5 Bicycle, 6 Dynamic**이다. 그림의 6개 표기는 실제 7개로 수정한다. class_map_version은 `received-yolo-7-v1`로 제안한다. Dynamic의 라벨 의미는 미확인이므로 원래 ID/name을 보존하고 다른 클래스에 합치거나 삭제하지 않는다. [정적 확인 근거](received-model-metadata-v0.2.json). 탐지 박스만으로 동일 차량의 지속 추적 ID를 만들지 않는다.
- `vlm`, `retrieval`, `report`, `human_review`는 다음 절을 따른다. 후보가 먼저 저장되고 설명 필드는 단계가 끝날 때 추가된다.

원본 S3 경로 예: `videos/{source_video_id}/original.mp4`. 결과 경로 예: `jobs/{job_id}/runs/{run_id}/...`. 재시도 산출물은 attempt 하위에 쓰고 채택한 manifest를 DB에 연결한다. 기존 경로에 재시도 파일을 무조건 덮어쓰지 않는다.

## 6. VLM·RAG·보고 계약

VLM 입력은 event ID, 실제 장면, 원본 시각, 탐지 메타데이터, 입력 근거 ID다. 출력:

- `status`, `summary`, `observations[{text, evidence_asset_ids, source_times_seconds}]`, `uncertainties`, `provider_model`, `prompt_version`.
- RAG 입력용 `operator_confirmed`는 Gemini의 독립적인 재확인(`true` 사고 장면 관찰, `false` 정상 장면 확인, `null` 판단 불가)이다. 사람 검토는 별도 `human_review`에 저장한다.
- 객체·충돌·피해·원인은 확인한 것과 추정을 구분한다. 서버가 JSON 형식과 근거 ID를 검증한다.

RAG 입력은 검증된 관찰 요약·질의·문서 종류/적용 지역 등 확인된 조건이다. 출력:

- `status`, `query`, `corpus_version`, `retrieval_version`, `citations[{document_id, title, source_url, section, excerpt, published_at, retrieved_at, relevance_note}]`.
- 법령·판례·사례·지침은 corpus_kind로 구분한다. 실제 판례를 확보하지 않았다면 ‘판례 검색 준비 중/자료 미확보’를 표시하며 일반 지침을 판례로 바꾸지 않는다.
- 검색 결과가 있어도 적용 근거가 약하면 insufficient_evidence. VLM이 추측한 과실·신호 위반을 확정 검색 조건으로 고정하지 않는다.

보고 출력은 `report_id`, `revision`, `status`, `text`, `source_event_id`, `evidence_asset_ids`, `citation_document_ids`, `limitations`, `generated_at`다. 영상 관찰/모델 추정/문서 근거/사람 검토를 구분한 템플릿 조립을 첫 구현으로 제안한다. 별도 LLM 재작성은 선택하며 사용 시 모델·프롬프트·근거 검증 기록을 추가한다.

## 7. 프로필과 미정 설정

### 2026-10-04 VLM 관찰 계약 확장

새 VLM 요청은 영상 binary part와 `vlm-input-v2` JSON을 함께 사용하며, 출력은 `scene-facts-v2`입니다.
`vlm.raw_output`에는 사고 여부·8개 위험/환경 특징의 `present/absent/unknown`, 근거 asset ID와
클립/원본 시각, 환경·관련 객체·사고 유형·불확실성이 저장됩니다.
`vlm.request.input`에는 실제 part 순서와 제공한 시각 매핑이 보존됩니다.
`vlm.validation`은 schema/provenance와 실제 관찰 정확도 상태를 구분합니다.
`rag_input`에는 관찰 특징과 기존 소비자를 위한 bool/null 별칭을 함께 보존합니다.
`operator_confirmed`는 VLM 판정 별칭이며 `human_review` 승인을 의미하지 않습니다.
기존 저장 결과는 유지합니다. 적용 방법과 실제 계약 예시는 [VLM 계약·평가 안내](../VLM_FACTS_VALIDATION.md)를 따릅니다.

`analysis_profile_id`는 객체/사고 가중치·해시, 모델별 입력 크기·샘플링·정규화·클래스 맵, 창 길이·간격, 판정/후처리, 근거 전후 길이, 최대 파일·영상 범위, VLM/RAG 버전을 참조한다. 미등록 프로필은 제출을 거절한다. 모델 이름만으로 R3D의 2초·16장·224 설정을 X3D-S에 이식하지 않는다.

개발 제안값: 한 요청 한 영상, UI 상태 조회 3초 간격, BE 회수 5초 간격·오류 시 backoff, GPU 동시 작업 1. 이 값들은 품질·응답시간 보장이 아니다. 최대 영상 길이·파일 크기·GPU timeout·재시도 상한·금액은 비용 측정 전 미정이며 실제 실행 프로필에 값을 채워야 한다.
