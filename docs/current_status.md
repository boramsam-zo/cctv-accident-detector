# 팀 서비스 현재 상태

## 작업 재개 요약 — 2026-09-26

| 항목 | 확인된 상태 |
|---|---|
| 설계 | Streamlit·FastAPI·S3·상시 Runpod GPU Pod·YOLO11s·X3D-S·VLM/RAG·보고·사람 검토 |
| 모델 역할 | X3D-S가 후보 구간을 찾고 YOLO가 후보 시각 장면의 객체 정보를 제공 |
| 문서 | PRD v0.2, 공통 계약, 역할 문서 6개, 가상 응답 8개, 요구사항 28개, 예정 QA 18개 |
| 수신 모델 | 전달 묶음 11개 파일의 manifest 크기·SHA256 일치. 모델 로드 없이 YOLO 7클래스·X3D epoch7/threshold0.5 정적 확인 |
| 미확인 | Pod GPU·지역·container image·재시작 정책, 업로드 영상 처리 pacing·heartbeat/checkpoint, Dynamic 뜻·표시 정책, 실제 모델 로딩/추론·PTS/coverage 연결, 서비스 통합·품질·비용 |
| 구현 | 기존 저장소는 기본 폴더와 안내 상태. 이번 변경은 문서이며 새로운 API·모델·배포 구현은 없음 |
| 다음 한 작업 | Dynamic 라벨 정의·표시 정책 확인, 이후 수신 결과의 공통 계약·시각·근거 연결 구체화 |

[전체 계획](../IMPLEMENTATION_PLAN.md) · [공통 계약](contracts/service_contract.md) · [진행 기록](PROGRESS.md).
