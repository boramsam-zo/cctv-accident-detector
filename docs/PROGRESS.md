# 팀 진행 기록

## 2026-09-27 — 업로드 영상 기반 실시간 시연 범위 확정

- 변경: 실제 CCTV/RTSP 연결을 첫 시연 범위에서 제외하고, 업로드한 영상 파일을 Pod가 원본 시간순으로 읽으며 후보를 완료 전에 부분 등록하는 방식으로 확정했다.
- 유지: 상시 Runpod GPU Pod, job/run 이력, worker heartbeat, S3 근거·manifest, VLM/RAG와 사람 검토.
- 결정: 시연은 원본 재생속도 1×, 현재 재생시각까지의 프레임만 사용하는 `file_realtime_1x` 기준이다.
- 확인 필요: UI 재생시각과 worker 처리 PTS 허용 오차, 진행률 계산, 중단 후 checkpoint 재개 범위.
- 미실행: 실제 업로드→Pod 시간순 추론→부분 후보 표시의 통합 시험.

## 2026-09-27 — 상시 Runpod GPU Pod 확정

- 변경: GPU 실행 방식을 Runpod Serverless에서 상시 GPU Pod로 확정하고, 제출/polling 계약을 상시 worker·heartbeat·camera session·실시간 event push 계약으로 교체했다.
- 유지: 녹화 영상의 job/run 이력, S3 manifest 검증, VLM/RAG 후속 처리, 사람 검토 구조는 유지한다.
- 후속 범위 변경: 실제 CCTV/RTSP 연결은 제외하고 업로드 영상 기반 시연으로 확정했다.
- 미실행: Pod 생성·결제, 모델 상시 로딩, 업로드 영상 부분 event 등록, 장애 복구 시험.

## 2026-09-27 — GPU 실행 계층 Runpod 전환 이력

- 변경: Modal 기반 비동기 호출 계약을 Runpod Serverless queue endpoint의 `/run` 제출, `runpod_job_id`, `/status` 회수 방식으로 교체했다.
- 이유: 프로젝트 GPU 제공자를 Runpod로 변경한다는 사용자 결정을 반영했다.
- 유지: S3 manifest를 영구 결과 기준으로 사용하고 DB lease·중복 방지·옛 run 격리·후속 VLM/RAG 처리 구조는 유지한다.
- 후속 결정: 같은 날 상시 GPU Pod 방식으로 확정해 위 항목으로 대체했다.
- 미실행: Runpod 계정·endpoint 생성, 유료 GPU 호출, container 배포, 실제 모델 추론 및 S3 연결.

## 2026-09-26 — 서비스 PRD v0.2 문서 준비

- 변경: 사용자 선택 아키텍처를 PRD·역할별 문서·공통 계약으로 정리. 기존 모델/학습 폴더 구조에 연결했다.
- 이유: 영역마다 API·상태를 다르게 해석하지 않도록 한 계약을 공유하고, 입력·산출물·완료 기준으로 개발을 나누기 위함.
- 모델 확인: 수신 .pt의 YOLO는 실제 7개 클래스여서 그림의 6개 표기를 수정. X3D 후보 시각 한 프레임에 YOLO가 객체 정보를 붙이는 흐름을 반영.
- 원본 근거: [수신 파일 메타데이터](contracts/received-model-metadata-v0.2.json). 가중치 파일 자체는 미포함. 정적 메타데이터 확인과 실행 검증을 구분했다.
- 문서 확인: JSON·상태·시간·클래스·상대 링크·파일 범위의 정적 검사 대상이다. 통합 QA 18개는 앞으로 실행할 시나리오다.
- 미실행: 새 모델 추론·학습·클라우드 배포·유료 호출·실제 API 통합 시험. 모델 품질/지연/비용의 전후 비교 없음.

## 이후 기록 양식

날짜·작업 영역 / 변경 이유 / 코드·설정·계약 버전 / 실제 실행 명령·환경 / 원본 결과 경로 / 전후 조건과 차이 / 확인 결과 / 미실행·남은 문제를 남긴다. 완료한 현재 상태는 current_status.md, 다음 TODO는 IMPLEMENTATION_PLAN.md에서 관리한다.
