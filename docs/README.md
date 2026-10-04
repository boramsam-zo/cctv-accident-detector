# 프로젝트 문서

[전체 PRD](../PROJECT_BRIEF.md) → [공통 계약](contracts/service_contract.md) → [Modal 추론 연결 계약](contracts/modal-inference-v1.md) → [역할별 문서](roles/README.md) 순서로 읽습니다.

현재 구현 요약은 [README 현재 상태](../README.md#현재-상태), 실행·검증 이력은 [진행 기록](PROGRESS.md)을 참고합니다.

첨부 청크 기반 검색·보고서·화면 연결 설계는 [RAG 적용 기획](RAG_INTEGRATION_PLAN.md)을 참고합니다. 청크 분석 수치와 출처 목록은 [분석 기록](rag/chunks-analysis.json)에 있습니다.
구현된 3회 호출 경로의 출력은 [기관 리포트 JSON 계약](contracts/agency-report-v1.md), 인덱스 초기화는 [RAG 데이터 관리](../data/rag/README.md)를 따릅니다.

| 문서 | 내용 |
|---|---|
| [프로젝트 폴더 구조](PROJECT_FOLDER_STRUCTURE.md) | 기존 모델·학습 패키지와 서비스 폴더 추가 시점 |
| [팀 공유·편집 안내](team_handoff.md) | 팀원 읽기 순서·역할 사이 변경 방법 |
| [요구사항](requirements.md) | 기능과 인수 기준 |
| [공통 계약](contracts/service_contract.md) | API·추론 입력/출력·상태·오류·검토 |
| [Modal 추론 연결 계약](contracts/modal-inference-v1.md) | 비동기 GPU 제출·S3 결과 회수 |
| [가상 응답](contracts/demo-analysis-cases-v0.2.json) | 화면/계약 검토용 사례 8개 |
| [모델 메타데이터](contracts/received-model-metadata-v0.2.json) | 실제 파일 해시·클래스·정적 설정 확인 |
| [통합 확인 시나리오](roles/validation.md) | 앞으로 실행할 QA 시나리오 18개 |
| [진행 기록](PROGRESS.md) | 실행·변경 이유·근거·미실행 |
| [개념 기록](LEARNING_LOG.md) | 설계 선택과 한계 |

이전 폴더 구조 문서에서 제안했던 PROJECT_CONTEXT.md, INFERENCE_CONTRACT.md, API_DOCS.md, TEST_PLAN.md의 역할은 현재 PRD·공통 계약·QA 문서에 모았습니다. 같은 내용을 이름만 바꿔 중복 관리하지 않습니다.
