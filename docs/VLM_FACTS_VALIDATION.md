# VLM 관찰 계약과 클립 평가

기본 프롬프트는 `scene-facts-v2`입니다. 사고 여부와 산길, 불꽃 인접 식생, 불꽃, 연기,
파편, 차로 점유, 사고 영향을 받은 사람, 산림 자체의 연소를 각각 `present / absent / unknown`으로 출력합니다.
가려지거나 화질이 부족해 확인할 수 없는 항목은 `unknown`입니다. 관찰 범위에서 명확히 없는 경우만 `absent`입니다.
사고 유형이 불명확하면 가장 가까운 유형을 선택하지 않고 `null`을 유지합니다.

## 영상 입력과 검증

`services/backend/scene_facts.py`의 `SceneFacts`가 실제 출력 계약입니다.
`docs/contracts/scene-facts-v2.example.json`은 영상 평가 결과가 아닌 구조 예시입니다.
기존 `proposed-*.json`은 과거 설계안이며 현재 계약은 이 문서와 런타임 스키마를 따릅니다.

VLM에는 `vlm-input-v2` JSON과 영상·이미지 binary part를 함께 보냅니다. JSON에는 이벤트와 후보 시각,
탐지 관찰, 각 part의 asset ID·순서·MIME·클립 원본 시작/종료 시각·프레임 원본 시각이 있습니다.
후보 점수와 탐지 박스는 사고 확정 근거로 사용하지 않습니다. 제공되지 않은 촬영 위치는 추측하지 않습니다.

확정·부재 관찰, 환경, 객체, 사고 유형에는 근거 asset ID가 필요합니다.
생성용 JSON Schema에도 확인/부재 항목의 최소 근거 개수와 해당 요청에서 제공한 asset ID 목록을 적용합니다.
`schema_version`과 `unknown` 같은 단일 고정값은 `enum`으로 전달하고,
확인/부재와 미확인 항목은 `anyOf`로 구분합니다. 생성 제약과 서버 검증을 함께 유지합니다.
Gemini가 지원하는 구조 출력 형식은 [공식 안내](https://ai.google.dev/gemini-api/docs/structured-output)를 참고합니다.
제공하지 않은 ID, 프레임에 대한 클립 시각, 범위를 벗어난 시각, 불일치하는 원본/클립 시각을 거부합니다.
시각 매핑이 없는 자료는 해당 시각을 `null`로 둡니다. 프롬프트를 교체해도 계약은 적용됩니다.
검증 실패는 VLM 실패로 저장되고 RAG 및 보고서 생성은 건너뜁니다.

`vlm.validation`의 schema/provenance 통과는 JSON·참조 무결성 검증입니다.
실제 영상 관찰 정확도는 `not_evaluated`로 별도 표시합니다. 기존 결과를 새 계약의 검증 완료 결과로 변경하지 않습니다.
`operator_confirmed`는 기존 UI 호환용 VLM 사고 판단 값이며 사람의 최종 승인이 아닙니다.

## 실행과 사람이 확인할 항목

개발 Compose의 backend는 변경 파일을 다시 읽습니다. worker는 재시작이 필요합니다.
일반 Compose는 이미지를 다시 빌드합니다. 새 환경 변수, DB 마이그레이션, 청크 재임베딩은 필요하지 않습니다.

```powershell
# 개발 Compose 사용 시
docker compose --env-file .env -f deploy/compose/compose.yaml -f deploy/compose/compose.dev.yaml restart worker
# 일반 Compose 사용 시
docker compose --env-file .env -f deploy/compose/compose.yaml --profile test up -d --build backend worker test-ui streamlit
```

1. E2E 화면에서 새 후보 클립을 직접 확인하고 `scene-facts-v2` 기본 프롬프트로 분석합니다.
2. 클립과 VLM 출력의 각 관찰, 근거 프레임, 원본 시각을 대조합니다.
3. “클립 평가용 결과 JSON 다운로드”로 결과를 저장합니다.
4. `docs/contracts/vlm-facts-labels.template.json`을 복사해 실제 event ID와 검토자를 입력하고,
   클립을 보고 정답을 작성한 다음 `clip_reviewed`를 `true`로 변경합니다. 모델 답을 정답으로 복사하지 않습니다.
5. 로컬에서 평가합니다. 이 도구는 외부 요청이나 영상 업로드를 하지 않습니다.

```powershell
.venv\Scripts\python.exe scripts/evaluate_vlm_facts.py --result .local/vlm-job-result.json --labels .local/vlm-labels.json --output .local/vlm-evaluation.json
```

출력은 상태 정확도, 잘못된 present 판정 수, 계약 실패 수, 항목별 혼동 행렬을 포함합니다.
정답 불일치 또는 계약 실패가 하나라도 있으면 종료 코드 1입니다. 현재 평가는 9개 관찰 상태를 비교하며,
객체 수·충돌 유형·날씨의 정확도는 직접 대조해야 합니다. 테스트의 합성 데이터는 실제 영상 정확도 수치가 아닙니다.
정상 주행, 실제 충돌, 가려진 충돌, 차량 화재, 연기만 있는 장면, 산길 화재, 실제 산림 연소를 포함해 평가하세요.

## RAG 연결

새 결과는 근거가 있는 `present` 관찰, 확인된 객체·환경·사고 유형으로 검색합니다.
자유 서술의 검색 키워드와 `unknown / absent` 관찰을 긍정 사실로 검색에 넣지 않습니다.
불확실성은 보고서 입력에 보존합니다. 기존 저장 결과는 기존 검색 방식으로 호환합니다.
검색 결과에는 청크의 적용 단계, 조건, 조치 주체와 예외 관련 메타데이터를 보존합니다.
실제 산림 연소가 미확인이면 `actual_forest_fire_required` 청크를 현재 산불 대응의 확정 근거로 사용한 보고서를 거부합니다.
기관별 전달 사항·현장 참고항목 UI와 사람의 최종 검토 흐름은 기존 방식으로 연결됩니다.
