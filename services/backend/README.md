# FastAPI 백엔드 (로컬 개발 구현)

[HTTP API v0.2](../../docs/contracts/api-spec-v0.2.md)의 영상·작업·근거 URL·검토 API와 Runpod 상시 GPU Pod용 내부 API를 구현했습니다. Pod는 등록·heartbeat 후 작업을 claim하고, 처리 중 event와 최종 manifest를 등록합니다. CPU 별도 프로세스가 검증된 S3 clip·frame을 Gemini에 보내 장면 설명을 저장합니다. RAG 문서 저장소는 아직 연결되지 않아 `insufficient_evidence/corpus_not_configured`를 표시합니다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `app.py` | 공개 API와 Pod 내부 API, 인증·멱등성·오류 응답 |
| `models.py`, `db.py` | 영상, 작업, Pod worker, 후보, 검토 DB 모델과 개발용 DB 초기화 |
| `pod.py` | Pod 등록·lease·manifest·S3 객체 검증 및 후보 등록 |
| `worker.py`, `run_worker.py` | Gemini 후속 작업과 별도 프로세스 진입점 |
| `gemini_vlm.py` | Gemini 구조화 응답과 근거 ID 검증 |
| `storage.py`, `video_probe.py` | S3 파일 접근과 ffprobe 영상 검사 |
| `settings.py` | 환경 변수 설정 |

## 팀 공통 환경 및 테스트

저장소 루트에서 Python 3.11과 uv를 사용합니다. `uv.lock`은 커밋하고 `.venv`는 Git에서 제외합니다.

```bash
uv sync --locked
uv run --locked pytest -q
```

테스트는 SQLite와 가짜 S3·Pod·Gemini로 실행되어 AWS 계정이나 API 키가 필요하지 않습니다. `ffprobe`도 주입된 테스트 대역을 사용합니다.

## 실제 서비스 로컬 실행

`ffprobe`(FFmpeg 도구)를 설치하고 `.env.example`을 `.env`로 복사해 `APP_API_KEY`, `POD_WORKER_TOKEN`, S3 설정, `GEMINI_API_KEY`를 채웁니다. 이 앱은 `.env`를 자동으로 읽지 않으므로 두 프로세스의 셸에 로드합니다.

```bash
set -a
source .env
set +a
uv run --locked uvicorn services.backend.app:create_app --factory --reload
```

다른 터미널에서 같은 환경을 로드한 뒤 다음 프로세스를 실행합니다.

```bash
uv run --locked python -m services.backend.run_worker
```

공개 API는 `Authorization: Bearer <APP_API_KEY>`, Pod 내부 API는 별도 `POD_WORKER_TOKEN`을 사용합니다. `X-Actor-Id`는 제한된 팀 데모용 값이며 실제 사용자 인증과 권한 분리는 아직 구현되지 않았습니다. SQLite는 로컬 개발용이고, EC2 공동 운영에는 PostgreSQL `DATABASE_URL`을 설정해야 합니다. `create_all()`은 개발용이므로 운영 배포 전 DB 마이그레이션을 추가해야 합니다.

## Pod 작업 흐름

Pod worker는 `POST /internal/v1/workers/register`로 인스턴스를 등록하고 heartbeat를 보낸 후 `POST /internal/v1/workers/{worker_instance_id}/claim`으로 queued run을 받습니다. `assignment=null`이면 대기합니다. 할당에는 S3 원본 bucket/key/SHA256, `job_id`, `run_id`, attempt별 `output_prefix`, profile ID가 포함됩니다. Pod는 처리 도중 `POST /internal/v1/runs/{run_id}/events`로 부분 event를 등록하고 마지막에 `POST /internal/v1/runs/{run_id}/complete`로 최종 manifest를 등록합니다. 상세 JSON은 [API 명세](../../docs/contracts/api-spec-v0.2.md)를 참고하세요.

manifest와 미디어는 할당된 attempt의 `output_prefix` 아래에 저장해야 합니다. DB에는 실제 객체 SHA256을 검증한 뒤 등록합니다. 프레임에는 `source_time_seconds`가 필요합니다. BE는 임의 HTTPS URL을 읽지 않습니다. Gemini에 보내는 전체 미디어 용량은 기본 18 MiB입니다.

## S3 예시 clip·frame으로 Gemini JSON 확인

로컬 전용 스크립트는 짧게 유효한 S3 presigned URL 두 개를 메모리에서 다운로드하고 Gemini에 전송합니다. URL·미디어는 저장하거나 출력하지 않습니다. `GEMINI_API_KEY`와 URL을 셸 환경 변수로 설정한 뒤 실행합니다.

```bash
export GEMINI_API_KEY='...'
export CLIP_PRESIGNED_URL='https://.../clip.mp4?...'
export IMAGE_PRESIGNED_URL='https://.../frame.png?...'
export EVENT_ID='event_000'
# Runpod 후보 시각이 있으면 CANDIDATE_TIME_S 설정
uv run --locked python -m scripts.preview_gemini_rag
```

출력은 [VLM → RAG 입력 계약](../../docs/contracts/vlm-rag-input-v1.md)의 JSON이다. 현재 URL이 만료되면 새 URL이 필요합니다. 클립과 이미지의 합계가 18 MiB를 넘으면 실행을 중단합니다. 이 스크립트는 백엔드의 검증된 S3 asset 경로를 우회해 로컬 예시를 확인하는 용도입니다.

## 현재 제한

- Runpod Pod의 GPU worker, 실제 가중치·분석 프로필 레지스트리는 아직 없습니다. 프로필은 `ANALYSIS_PROFILE_ID` 하나만 허용합니다.
- 만료된 lease의 안전한 회수·재시도, 장기 운영용 동시성 제어, 접근 권한 분리, DB 마이그레이션은 후속 작업입니다.
- RAG 문서 원문이 없으며 Gemini 입력 영상의 외부 전송·보관 정책은 배포 전 결정해야 합니다.
