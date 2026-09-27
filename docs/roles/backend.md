# BE — FastAPI·상태·작업 연결

기준: [PRD](../../PROJECT_BRIEF.md) · [공통 계약](../contracts/service_contract.md). API/enum을 이 문서에서 별도로 재정의하지 않는다.

## 책임

영상 접수·검증·S3 저장, 영구 작업 기록, Runpod Pod worker 상태, 처리 중 부분 event와 최종 결과 등록, VLM/RAG/보고 순서 관리, 화면 조회, 사람 검토 저장을 담당한다. API 요청과 장시간 후속 작업을 분리하되 초기에는 같은 저장소·DB를 쓰는 별도 작업 프로세스로 구성한다.

## 구현 단위

| 단위 | 입력→출력 | 확인할 실패 |
|---|---|---|
| 영상 API | 파일→검증된 video·S3 참조 | 손상/형식/크기/저장 실패, 중복 접수 |
| job API | video+profile→job/run 대기 기록 | 미등록 프로필, 동일 키의 다른 요청 |
| worker API | Pod 등록·heartbeat·부분 event→영구 상태·검증된 결과 | heartbeat 만료, 중복·지연 event, worker 재시작 |
| enrichment worker | 후보·장면→VLM/RAG/report | API timeout·형식 오류·검색 실패·근거 부족 |
| 조회 API | job/run/asset→허용된 결과·URL | 다른 run 혼합, 만료 URL, 접근 불가 |
| review API | 사람 판단→변경 이력 | 오래된 revision·중복 제출·다른 event |

## DB 제안

PostgreSQL에 videos, jobs, runs, events, assets, reports, reviews와 stage_tasks를 둔다. 문서/청크/검색 인덱스는 RAG 담당과 연결한다. 큰 영상·프레임 bytes는 S3에 두고 DB에는 참조·해시·버전을 저장한다.

run 상태와 active_run_id, 모델/입력 버전, pod_id·worker_instance_id, heartbeat, 처리 PTS/checkpoint, stage 상태, lease 만료·시도 수·오류를 저장한다. 요청자+endpoint+Idempotency-Key, run+sequence, run+event, run+manifest 식별자에는 유일성 검사를 둔다. 임의의 URL을 실행 입력으로 받지 않고 등록된 S3 객체만 연결한다.

## 작업 안정성

- POST /jobs는 DB 커밋 후 202를 반환한다. GPU 완료까지 HTTP 연결을 유지하지 않는다.
- 별도 프로세스는 DB lease로 작업을 점유한다. 장애 후 만료된 lease를 회수하되 외부 호출 접수 여부를 먼저 확인한다.
- worker heartbeat와 실제 영상 처리 진행을 구분한다. heartbeat가 살아 있어도 처리 PTS가 정체되면 run을 degraded 상태로 진단하고 오류를 기록한다.
- S3 manifest를 검증한 뒤 결과를 등록한다. 파일 목록만 있다고 completed로 표시하지 않는다.
- 후속 단계 실패 시 후보를 보존하고 부분 보고를 만든다. 재처리는 필요한 단계만 실행하도록 stage_tasks와 보고 revision을 사용한다. 첫 버전의 사용자 재시도 API는 전체 새 run이며 단계별 수동 재시도는 내부 운영 경로로 제안한다.
- VLM/RAG는 GPU 함수가 끝난 뒤 BE에서 호출한다. 응답 원문·검증 오류는 민감 내용을 줄여 기록하고 사용량을 남긴다.

## 받을 것·넘길 것

모델 담당에게 manifest와 model profile, FE에게 API 명세·가상 응답·오류 사례, VLM/RAG에게 후보별 입력 및 저장 필드, 인프라에게 배포 프로세스/환경변수 이름/권한 범위를 전달한다. `.env` 실제 값은 문서·저장소에 넣지 않는다.

## 첫 작업과 완료 기준

먼저 외부 GPU 호출 없이 가상 worker로 등록→heartbeat→부분 event→최종 결과→검토 저장을 연결한다. 이후 한 업로드 영상의 Runpod GPU Pod 실제 연결을 별도로 확인한다.

완료 확인: 프로세스 재시작 후 작업 복구, 중복 요청 하나의 job 반환, 동일 결과 중복 등록 방지, 옛 run 결과 격리, 손상 manifest 거절, 실패를 정상으로 표시하지 않음, 검토 충돌 감지. [QA 문서](validation.md)에 실제 결과·로그를 남긴다.
