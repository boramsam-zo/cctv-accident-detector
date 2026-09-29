# PRD·역할 문서 수정 요청문 — v0.2

2026-09-26. [실제 PRD](../PROJECT_BRIEF.md), [역할 안내](roles/README.md), [공통 계약](contracts/service_contract.md)이 현재 원본이다. 아래는 이후 수정 작업에 복사할 프롬프트다.

```text
기존 CCTV 서비스 PRD와 역할별 개발 문서를 수정해 줘.
먼저 PROJECT_BRIEF.md, docs/contracts/service_contract.md,
docs/contracts/modal-inference-v1.md, docs/roles/README.md,
README.md의 현재 상태, docs/PROGRESS.md, IMPLEMENTATION_PLAN.md를 읽어라.
GPU 실행 방식은 Modal 계약을 기준으로 한다.

확정된 사용자 선택:
- 팀 개발·발표용 전체 서비스 PRD다. 개인별 업무 배정은 하지 않는다.
- 대상은 관제 담당자, 프로젝트 영상 검토자, 경찰·사고 대응 담당자다.
- Streamlit, FastAPI, S3, Modal GPU 비동기 오프라인 추론, YOLO11s 7개 클래스(수신 체크포인트 기준),
  X3D-S, Gemini VLM, 향후 RAG 유사 사례·판례/문서 검색과 보고 초안,
  사람의 최종 검토, PostgreSQL, CloudWatch/Modal Dashboard를 반영한다.
- X3D-S는 후보 구간을 판별하고 YOLO는 해당 영상의 객체 정보를 제공한다.
  X3D 후보→원본 장면→YOLO 순서를 제안하며 YOLO crop을 X3D에 넣지 않는다.
- 수신 모델의 클래스·해시·정적 설정은 received-model-metadata-v0.2.json을 따른다.
  Dynamic 의미, 실제 모델 동작,
  RAG 문서 확보·배포 크기·예산은 확인된 기록만 확정으로 쓴다.

문서 운영:
- 전체 목표·범위는 PROJECT_BRIEF.md에,
  공통 필드·상태·API는 docs/contracts/service_contract.md에 둔다.
- FE·BE·모델·VLM/RAG·인프라·QA 문서에는
  책임, 입력, 산출물, 첫 작업, 실패 처리, 완료 기준을 쓴다.
- API나 상태를 각 문서에서 따로 정의하지 않는다.
- 기존 R3D 실험·읽기 전용 화면과 새 서비스 구현 상태를 구분한다.
- 모델 점수를 실제 사고 확률, 후보 시각을 미래 사고 예측으로 표현하지 않는다.
- 오류·미분류·후보 없음·RAG 근거 부족을 구분한다.
- 바뀐 이유·전후 차이·실제 확인·미실행·다음 작업을 중앙 기록에 남긴다.
- 문서 개정만으로 서비스 배포·유료 사용·실제 영상 전송을 실행하지 않는다.
- 새 결정을 반영하되 기존 기록·원본 결과·과거 전달 ZIP을 보존한다.

요청한 수정 사항을 실제 파일에 반영하고,
역할 사이 모순·상대 링크·가상 JSON·문서 버전을 점검해 보고하라.
```
