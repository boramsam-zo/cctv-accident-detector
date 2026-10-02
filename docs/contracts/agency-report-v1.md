# 기관 리포트 JSON v1

현재 구현: `services/backend/rag.py`, `worker.py`, `apps/streamlit/app.py`.

정상 후보별 호출: Gemini 영상 분석 → 단일 질의 임베딩 → 로컬 hybrid 검색 → Gemini 최종 JSON.
등록 시 문서 임베딩을 생성하며 영상 처리에서 재생성하지 않는다.
기본 활성화는 Settings.from_env의 `RAG_ENABLED=true`다.

최종 JSON의 필드:

- `summary`: 영상 관찰 요약.
- `agencies[]`: `agency`, `role`, `reason`, `selection_status=supported/conditional`,
  `conditions_to_confirm[]`, `citation_chunk_ids[]`.
- `limitations[]`: 자료·관찰·적용 조건의 불확실성.

기관은 코퍼스의 10개 분류 중 여러 개를 선택할 수 있다. JSON schema에서 추가 필드는 금지한다.
서버는 인용 ID 존재·기관 태그 일치·기관 중복·조건부 선택의 확인 조건을 검증한다.
`operator_confirmed=false`인 장면은 기관 배열이 비어야 한다.
구조·구급은 소방 역할에, 의료지원은 응급의료기관 역할에 표현한다.
신고 방법·전화번호·직접 연락·특정 병원 선정은 출력 범위에 포함하지 않는다.
조건 판단 자체는 생성 모델이 수행하므로 실제 적용의 의미 검수는 별도로 필요하다.

검증된 JSON은 `report.structured`에 저장하고 기존 `text`, `limitations`, `agencies`,
`citation_document_ids`, `citation_chunk_ids`, `corpus_version`으로도 연결한다.
검색된 청크의 원본 content·URL·해시는 서버가 채우고 생성 모델이 바꾸지 않는다.

VLM 실패: RAG skipped, 원본 근거 유지, run partial.
검색 실패/인덱스 미생성: RAG failed, 생성 호출 생략, fallback report와 run partial.
검색 근거 부족: RAG insufficient_evidence, 빈 기관의 최종 JSON 생성, 다른 오류 없으면 run completed.
JSON 생성/검증 실패: report generation_status failed, 영상 관찰과 검색 인용 유지, run partial.
기존 VLM 실패 재시도는 동작하며 RAG/report 단독 재시도는 아직 없다.

관련 실행 안내: [데이터 관리](../../data/rag/README.md).
