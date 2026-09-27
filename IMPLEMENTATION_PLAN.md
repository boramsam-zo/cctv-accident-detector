# 팀 서비스 구현 계획

기준: [PRD](PROJECT_BRIEF.md) · [공통 계약](docs/contracts/service_contract.md) · [현재 상태](docs/current_status.md).

## 완료된 문서 준비

- [x] Streamlit·FastAPI·S3·상시 Runpod GPU Pod·YOLO11s·X3D-S·VLM/RAG·보고·사람 검토 PRD.
- [x] FE·BE·모델·VLM/RAG·인프라·QA 문서와 공통 API/데이터 계약 초안.
- [x] 가상 응답 8개, 요구사항 28개, 앞으로 실행할 QA 시나리오 18개.
- [x] 전달 모델 11개 파일의 크기·SHA256 대조, YOLO 7클래스·X3D epoch7/threshold0.5 정적 확인.

## 다음 작업

1. Dynamic 클래스의 라벨 정의와 화면 표시 정책을 확인한다.
2. API/상태·모델 출력 계약을 검토하고 가상 응답으로 FE/BE 흐름을 맞춘다.
3. 받은 추론 결과를 계약으로 변환하고 실제 PTS·coverage·근거 파일 생성 차이를 구현 계획에 반영한다.
4. 승인된 환경·입력·사용량 안에서 한 업로드 영상의 S3→Runpod GPU Pod 시간순 분석→부분 event→최종 결과 연결을 확인한다.
5. VLM·RAG·보고·검토 저장을 연결하고 통합 시나리오를 확인한다.
6. 고정된 평가 자료·정답·판정 기준으로 모델 품질을 별도로 평가한다.

새 서비스 구현·배포·실제 모델 추론은 이 문서 작업에서 수행하지 않았다. 별도 R3D 실험의 데이터·모델·평가 TODO는 원래 실험 저장소에서 유지한다. 이 계획은 담당자 이름·일정을 배정하지 않는다.
