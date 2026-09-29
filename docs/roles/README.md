# 역할별 개발 문서와 편집 규칙

이 폴더는 사람 배정표가 아니다. 새로 참여한 팀원이 담당 영역의 입력·산출물·연결점·완료 기준을 찾는 안내다. 한 사람이 여러 영역을 맡아도 된다.

## 읽기 순서

1. [전체 PRD](../../PROJECT_BRIEF.md): 목표·범위의 이전 설계 기록. GPU 실행은 현재 [Modal 계약](../contracts/modal-inference-v1.md)을 따른다.
2. [공통 API·데이터 계약](../contracts/service_contract.md): 필드·상태·버전·오류.
3. 자기 영역 문서와 연결할 상대 영역 문서.
4. [요구사항](../requirements.md), [통합 확인 시나리오](validation.md).

| 영역 | 편집할 문서 | 준비할 결과 |
|---|---|---|
| FE | [frontend.md](frontend.md) | Streamlit 사용자 흐름·상태 표시·API 연결 |
| BE | [backend.md](backend.md) | FastAPI·DB·작업 제출/회수·검토 저장 |
| 모델 | [model.md](model.md) | YOLO11s/X3D-S 입출력·Modal 근거 생성 |
| VLM/RAG | [vlm_rag.md](vlm_rag.md) | 장면 설명·문서 검색·출처·보고 초안 |
| 인프라 | [infrastructure.md](infrastructure.md) | 배포 위치·권한·비용·보관·관측 |
| QA·통합 | [validation.md](validation.md) | 실제 인수 기록·누락/중복/복구·품질 구분 |

## 무엇을 어디에 기록하나

| 바뀌는 내용 | 원본 문서 |
|---|---|
| 사용자 가치·기능 포함/제외 | PROJECT_BRIEF.md |
| API·필드·상태·모델 공통 출력 | docs/contracts/service_contract.md |
| 담당 영역의 구현 방식·파일·로컬 확인법 | 해당 역할 문서 |
| 요구사항과 인수 조건 | docs/requirements.md |
| 전체 TODO와 다음 작업 | IMPLEMENTATION_PLAN.md |
| 현재 확인된 사실 | docs/current_status.md |
| 실행·변경 이유·테스트·남은 문제 | docs/PROGRESS.md |
| 개념·설계 선택의 이유 | docs/LEARNING_LOG.md |

역할 문서마다 다른 TODO/실행 일지를 쌓지 않는다. 역할 문서에는 책임과 완료 기준을 두고, 현재 완료 여부·원본 로그는 중앙 기록을 링크한다.

## 함께 수정하는 방법

자기 영역의 상세는 직접 수정한다. 다른 영역이 사용하는 필드가 바뀌면 **공통 계약 수정→영향 영역 표시→가상 응답 갱신→연결 확인**을 같은 변경 묶음으로 준비한다. 깨지는 변경은 계약 버전을 올리고 구버전 해석 방법 또는 전환 시점을 남긴다. 담당자 이름·마감일은 요청 없이 임의 배정하지 않는다.

새 구현을 시작할 때 아래 요청문에서 담당 영역만 바꿔 사용한다.

```text
이 프로젝트의 [FE/BE/모델/VLM·RAG/인프라] 영역을 맡았다.
먼저 PROJECT_BRIEF.md, docs/contracts/service_contract.md,
docs/roles/의 해당 문서와 docs/current_status.md를 읽어라.
최신 사용자 선택과 제안·미정·구현 완료를 구분하라.
공통 계약에 맞춘 이번 작은 작업의 입력·출력·완료 기준을 먼저 설명하라.
가상 데이터를 쓰면 명확히 표시하고 실제 모델 성과로 보고하지 마라.
공통 필드를 독자적으로 바꾸지 말고 계약과 영향 문서를 함께 갱신하라.
코드·원본 결과·변경 이유·실제 검증·미실행 항목을 중앙 기록에 남겨라.
배포·유료 실행·외부 데이터 전송은 문서 기획 완료와 구분하라.
```
