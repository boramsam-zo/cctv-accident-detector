# rag_output 양식을 위한 RAG·VLM 계약 권고안

이 문서는 설계 제안입니다. 실행 스키마·프롬프트·검색기·기존 보고서는 변경하지 않습니다.
JSON 예시는 가상 형식 예시이며 실제 영상의 분석 결과가 아닙니다.
참조 양식: 사용자가 제공한 `rag_output.txt`.

## 1. 확인한 데이터와 현재 차이

`data/rag/chunks.jsonl`은 609청크입니다. 대응·법령 275청크와 통계 334청크로 나뉩니다.
대응 자료는 법률 67, 시행령 19, 행정규칙 172, 시행규칙 3, 공식 지침 14청크입니다.
기관 태그는 중복 허용이며 경찰 224, 소방 29, 도로관리기관 16, 산림기관 11청크입니다.
원문 성격은 공식 원문 계열 261청크와 출처 기반 요약 14청크입니다.
원문을 PDF에서 직접 재검증한 것이 아니라 청크 본문·메타데이터를 분석했습니다.
`source_file`에 기록된 PDF/TXT/CSV 원본은 현재 저장소 경로에는 없습니다.

209청크의 `conditions_status`는 `inline_source_text; not_exhaustively_structured`입니다.
적용 조건 배열이 존재해도 구체 요건이 모두 추출된 것은 아닙니다. 원문 본문도 전달해야 합니다.
기관 태그가 빈 청크는 12개, 조치 주체가 빈 청크는 10개입니다. 자동 확정 대신 메타데이터 검수 대상으로 둡니다.
`referenced_articles`가 있는 대응 청크는 94개, `related_chunk_ids`가 있는 청크는 20개입니다.

현재 VLM은 불꽃·차로 점유 등의 bool/null을 생성하지만 연기·파편·산림 연소 등은 별도 필드가 없습니다.
`operator_confirmed`는 모델의 장면 재확인 값인데 사람 확인처럼 보이는 이름이므로 새 버전에서는
`accident_presence`와 별도 `human_review`로 구분하는 것이 좋습니다.
현재 보고서 JSON은 summary/agencies/limitations 중심이라 예시의 모든 절을 고정 생성하기에는 부족합니다.

## 2. 처리 구조

1. 백엔드: 카메라 등록 정보, 원본 시각, 클립 시각 매핑과 실제 미디어를 준비합니다.
2. VLM: 영상에서 관찰 가능한 사실만 구조화하고 각 사실에 영상 근거를 연결합니다.
3. 백엔드: 미디어 ID·시각을 검증하고 등록 정보를 모델 관찰과 별도로 결합합니다.
4. RAG: 관찰 사실에서 여러 검색 질의를 만들고 기관·조치별로 근거를 조회합니다.
5. 조건 평가: 연락 여부, 조치 적용 단계, 주체와 협조 주체를 근거별로 평가합니다.
6. 보고 생성: 전달 사항·요청 사항·현장 대응 참고를 출처 ID와 함께 JSON으로 생성합니다.
7. 서버 검증·렌더러: JSON 검증 후 고정된 여섯 절을 Markdown/Streamlit으로 렌더링합니다.

최초 VLM에는 법령 청크 전체를 보내지 않습니다. 영상 관찰과 법령 적용 평가의 입력을 구분합니다.
후속 보고 생성은 검증된 장면 JSON과 검색 청크를 사용하며 영상 바이트를 다시 전송할 필요가 없습니다.
예시 양식은 모델에게 Markdown을 자유 생성시키기보다 서버 템플릿으로 고정합니다.

## 3. VLM 입력과 출력

입력 예시: `contracts/proposed-vlm-request-v2.example.json`.
출력 예시: `contracts/proposed-scene-facts-v2.example.json`.

입력은 JSON 텍스트 파트와 원본 클립·대표 프레임의 실제 미디어 파트를 함께 보냅니다.
JSON의 asset_id·part_index는 모델이 응답에서 올바른 미디어를 참조하도록 하는 연결 정보입니다.
예시의 part_index는 JSON 텍스트 파트를 제외한 미디어 파트 배열의 인덱스입니다.
클립이나 영상 바이트를 JSON 문자열 안에 넣지 않습니다.
원본 클립을 기본으로 하고 객체 표시 영상·빨간 박스는 보조 자료임을 표시합니다.
카메라 위치·관할·등록 시각은 백엔드 소유 정보입니다. VLM이 지명·좌표·관할을 생성하게 하지 않습니다.

모든 관찰값은 `present/absent/unknown`과 근거를 묶습니다.
`absent`는 해당 영역을 충분히 관찰해서 없음을 확인한 경우에만 사용합니다.
가림·짧은 클립·화질 때문에 보이지 않으면 unknown입니다.
부상 상태는 영상에 사람이 보이는지와 다른 값이며, 확인되지 않은 부상·피해는 보고의 확인 필요 사항으로 남깁니다.
사고 유형이 불명확하면 가장 가까운 유형을 억지로 고르지 않고 null로 둡니다.
현재 운영 enum과 연결하려면 시간대는 day/night/null, 날씨는 clear/cloudy/rain/snow/fog/null을 유지합니다.

시각은 클립 내부 시각과 원본 시각을 분리합니다. 백엔드가 manifest의 매핑으로 원본 시각을 계산·검증합니다.
프레임 근거는 등록된 source_time_seconds만 허용합니다.
이벤트 ID는 백엔드가 채우거나 응답과 대조합니다. 인간 검토 결과는 VLM이 생성하지 않습니다.

## 4. 청크와 검색 설정

원본 content·content_sha256·chunk_id를 유지하고 전면 재청킹부터 시작하지 않습니다.
기존 조문·항·호와 관련 조건을 함께 유지하는 의미 단위 청킹을 사용합니다.
추가로 대형 목록을 나눌 경우 상위 조문의 주체·조건을 각 하위 청크에 연결하고 parent_chunk_id를 둡니다.
편집 메타데이터를 공식 법령 본문으로 취급하지 않습니다.

유지·전달할 메타데이터:

- 출처: document_id, chunk_id, title, section, source_url, source_version_url, content_sha256.
- 버전: effective_from/to, effective_to_inclusive/status, verification_status, source_checked_at, latest_status.
- 대상과 주체: agencies, actors, audience, report_uses.
- 조건: scenario_tags, retrieval_conditions, application_conditions, conditions_status,
  application_stage, conditional_actions, related_chunk_ids, referenced_articles.
- 본문 성격: text_origin, content_role.

현재 검색 결과에는 application_stage/conditional_actions/related_chunk_ids와 conditions_status 등이 누락됩니다.
해당 값을 후속 생성 컨텍스트까지 전달해야 산불 전이 위험 단계와 실제 산불 대응 단계를 구분할 수 있습니다.

권장 설정 시작값은 기존 768차원 임베딩, pgvector 코사인 검색 + 한국어 BM25 + RRF를 유지합니다.
각 질의에서 dense top-20~30, BM25 top-20~30을 가져와 RRF로 합치고 최종 전체 8~12개 근거를 검수합니다.
이 값은 실험 시작값이며 검색 품질 검증으로 조정해야 합니다. 기존 similarity 0.35도 확정 기준이 아닙니다.
기관별 검색은 질의 임베딩 요청 수를 늘릴 수 있으므로 모든 질의를 매번 실행하지 말고 관찰된 위험만 대상으로 합니다.

질의 묶음 예시:

- 일반 사고: 교통사고 초동조치·2차 사고 예방·현장 보존.
- 관찰된 불꽃: 차량 화재·구조 구급·대피 조건·소방 대응.
- 산림 인접 가능성: 불씨·산불 전이 위험·관할 확인·기관 협조.
- 실제 산림 연소 확인: 산불 현장 지휘·지원·협조 조건.
- 차로 점유 관찰: 교통 통제·도로 장애·회복·도로관리기관.

사실이 unknown이면 그 사실을 true로 강제 필터하지 않습니다. 확인 필요 조건을 찾는 보조 질의로 사용합니다.
통계 334청크는 대응 근거 검색에서 제외하고, 통계 영역이 필요할 때 별도 질의·출력으로 분리합니다.
현재 코퍼스에 판례 유형이 없으므로 판례를 생성하지 않습니다.
경찰 비중이 높아 전역 top-k만 사용하면 소방 등 기관 근거가 밀릴 수 있습니다.
기관별 후보 확보와 문서·조문 중복 제거를 함께 적용하되 기관별 슬롯을 채우기 위해 관련 없는 근거를 강제로 넣지 않습니다.
related_chunk_ids는 조건·예외·협조를 보완할 때 제한적으로 확장하며 검색 유사도만으로 실행 주체를 정하지 않습니다.
촬영일 기준 유효기간을 우선 사용하고 촬영일이 없으면 생성일 기준임을 출력합니다.
effective_to=null은 현재도 유효하다는 독립 검증 결과가 아닙니다.

## 5. 기관 선택과 조건 평가

기관 선택과 구체 조치 적용을 분리합니다. 연락 검토가 가능해도 지휘·출동·진화 등 모든 조치가 적용되는 것은 아닙니다.
권장 필드:

- contact_status: contact_target / conditional / not_selected.
- evidence_status: supported / insufficient_evidence.
- trigger_feature_ids: 관찰 사실과의 연결.
- unmet_conditions: 조건마다 met / not_met / unknown 및 근거.
- field_response_items[].actor, actor_role: 실행 주체와 협조 주체 구분.
- field_response_items[].applicability: applicable / conditional / not_applicable.

예시의 산림기관 '확산 확인 후 조건부' 문구를 모든 산길 화재의 고정 규칙으로 사용하지 않습니다.
실제 청크 `scenario-forest_01~03`은 risk_or_notification 단계,
`scenario-forest_04~07`, `09~11`은 actual_forest_fire_required 단계 메타데이터가 있습니다.
`scenario-forest_02-576ef0d9a955`는 항별 조건과 동작을 conditional_actions로 제공합니다.
영상의 '산이 보임'을 법정 산림인접지역 확인으로 치환하지 않고 카메라/GIS 등록 정보나 현장 확인값을 사용합니다.
이 구분은 청크에 기록된 조건을 보존하기 위한 설계이며 해당 법령의 현행성·실제 적용을 새로 검증한 결과는 아닙니다.

소방기본법 제26조 청크에는 경찰·소방이 모두 agencies로 태그되어 있으나 actors에는 소방의 명령 주체와
경찰 협조가 구분됩니다. agency 태그만으로 경찰에 같은 명령 권한을 부여하지 않습니다.
본문과 application_conditions를 보존한 주체·조건 검증을 적용합니다.

조건부 기관이 검색 근거 부족일 때도 최종 보고에 남길 수 있도록 빈 citation 목록과
insufficient_evidence를 허용합니다. 구체 현장 조치를 생성하지 않습니다.
기존 AgencyRecommendation은 citation_chunk_ids가 최소 1개라 이 경우를 표현할 수 없으므로 새 보고 계약이 필요합니다.
Streamlit 카드에는 contact_status=contact_target만 표시합니다. 전체 보고·JSON에는 조건부 기관도 보존합니다.

## 6. 최종 보고 JSON과 고정 출력

권장 top-level 구조:

```json
{
  "schema_version": "incident-response-report-v1-proposal",
  "event_id": "...",
  "incident_overview": {},
  "visual_observations": [],
  "agency_notifications": [],
  "field_response_references": [],
  "items_to_confirm": [],
  "references": [],
  "limitations": [],
  "provenance": {}
}
```

서버 렌더러가 다음 여섯 절을 항상 같은 순서로 만듭니다.

1. 사고 개요: description, 카메라·등록 위치, 후보 원본 시각, 관련 차량·사람 상태.
2. 영상 관찰 및 판단 불가 항목: 특징별 상태, 영상 근거 ID·시각, unknown 사유.
3. 관제의 전달·요청 사항: 기관 이름·contact_status·선정 이유·연락 경로·전달 항목·확인 요청·문서 인용.
4. 현장 대응 참고: 기관별 text, actor, actor_role, applicability, conditions, citation_chunk_ids.
5. 확인 필요 사항: VLM 불확실성과 기관·조치 조건 중 unknown 항목을 중복 제거.
6. 관련 근거: R1/R2 표시 번호, 실제 chunk_id, title, section, excerpt,
   본문 성격, 조치 주체, 적용 조건, URL, 유효기간, 검증 상태.

연락 경로는 별도 agency_contact_directory에서 서버가 채웁니다.
경찰 관제 연계망 같은 표시명과 관할 연락처 등록 상태를 관리하고 모델이 전화번호·관할 기관명을 생성하지 않게 합니다.
등록 정보가 없으면 '관할 연락처 등록 필요'를 표시합니다. 실제 연락·출동 수행 여부와 구분합니다.

LLM은 실제 chunk_id만 사용합니다. 서버가 최초 인용 순서로 R1/R2를 배정하고 같은 청크는 번호를 재사용합니다.
원문 excerpt·URL·해시는 원본 청크에서 서버가 채웁니다. LLM이 원문을 다시 쓰거나 URL을 생성하지 않게 합니다.
전달 사항은 관찰 근거에, 현장 참고는 문서 근거에 연결해 서로 다른 종류의 증거를 혼용하지 않습니다.

## 7. 검증과 구현 순서

검증: 알려진 미디어 ID, 클립/원본 시각 범위, unknown 처리, 문서 ID 존재,
기관-주체 일치, 항목별 적용 조건, reference 연결, 조건부 기관 표시 제한,
원문/요약 표시와 카메라 등록 정보 보존을 검사합니다.

신규 스키마는 추가Properties 금지의 JSON Schema로 정의하고 백엔드 Pydantic으로 재검증합니다.
현재 `response_json_schema` 방식과 단일 최종 보고 생성 요청을 재사용할 수 있습니다.
기존 보고서는 저장 버전으로 계속 렌더링하고 신규 요청부터 새 계약을 적용합니다.

권장 구현 순서는 VLM request/scene-facts 계약 → 누락 메타데이터 전달 →
기관별 검색·조건 평가 → 새 report JSON → 고정 Markdown/Streamlit 렌더러입니다.
산길+차량 불꽃, 실제 산림 연소, 차로 점유, 정상 주행, 관찰 불가, 검색 근거 부족의
고정 사례로 기대 기관·금지 조치·인용 정확성을 비교합니다.
형식 예시를 실제 영상 검증이나 법령 적용 검수의 대체물로 사용하지 않습니다.
