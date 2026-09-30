# FastAPI 백엔드 (로컬 개발 구현)

[HTTP API v0.2](../../docs/contracts/api-spec-v0.2.md)의 영상·작업·근거 URL·검토 API를 유지합니다. 별도 작업 프로세스가 Modal GPU 작업을 제출하고 S3의 결과 manifest와 clip·frame을 검증한 뒤 Gemini에 전달합니다. RAG 문서 저장소는 아직 연결되지 않아 `insufficient_evidence/corpus_not_configured`를 표시합니다. [Modal 연결 계약](../../docs/contracts/modal-inference-v1.md)을 참고하세요.

## 파일

| 파일 | 역할 |
| --- | --- |
| `app.py` | 공개 API, 인증·멱등성·오류 응답 |
| `models.py`, `db.py` | 영상, 작업, Modal call ID, 후보, 검토 DB 모델과 SQLite 테스트 초기화 |
| `modal_service.py` | Modal 비동기 제출·회수와 S3 결과 검증 |
| `worker.py`, `run_worker.py` | Modal 회수·Gemini 후속 작업과 별도 프로세스 진입점 |
| `result_state.py` | Modal 작업의 초기 공개 결과와 단계 상태 생성 |
| `gemini_vlm.py` | Gemini 구조화 응답과 근거 ID 검증 |
| `storage.py`, `video_probe.py` | S3 파일 접근과 ffprobe 영상 검사 |
| `settings.py` | 환경 변수 설정 |

## 팀 공통 환경 및 테스트

저장소 루트에서 Python 3.13과 uv를 사용합니다. `uv.lock`은 커밋하고 `.venv`는 Git에서 제외합니다.

```bash
uv sync --locked --group dev
uv run --locked pytest -q
```

테스트는 SQLite와 가짜 S3·Modal·Gemini로 실행되어 AWS 계정이나 API 키가 필요하지 않습니다. `ffprobe`는 주입된 테스트 대역을 사용합니다.

## 실제 서비스 로컬 실행

`ffprobe`(FFmpeg 도구)를 설치하고 `.env.example`을 `.env`로 복사해 `APP_API_KEY`, 실제 S3 설정, `GEMINI_API_KEY`, Modal 토큰·환경을 채웁니다. Modal SDK 설치 및 GPU 앱 배포는 [Modal 안내](../../deploy/modal/README.md)를 따릅니다. 현재 SDK는 별도 설치하므로 설치 후 서버·작업 프로세스는 `uv run --no-sync`로 실행합니다. 이 앱은 `.env`를 자동으로 읽지 않으므로 두 프로세스의 셸에 로드합니다.

```bash
set -a
source .env
set +a
uv run --no-sync uvicorn services.backend.app:create_app --factory --reload
```

다른 터미널에서 같은 환경을 로드한 뒤 다음 프로세스를 실행합니다.

```bash
uv run --no-sync python -m services.backend.run_worker
```

공개 API는 `Authorization: Bearer <APP_API_KEY>`를 사용합니다. `X-Actor-Id`는 제한된 팀 데모용 값이며 실제 사용자 인증과 권한 분리는 아직 구현되지 않았습니다. SQLite는 테스트용이며 PostgreSQL 스키마는 Alembic으로 적용합니다. GPU 결과 회수에는 별도 작업 프로세스가 반드시 실행되어야 합니다.

## 로컬 PostgreSQL과 실제 S3 연결

전체 E2E 검증에는 실제 AWS S3 버킷, Modal GPU 함수와 Gemini API를 사용합니다. `S3_ENDPOINT_URL`은 비워 둡니다.

Docker와 `ffprobe`를 설치한 뒤 저장소 루트에서 `.env.local.example`을 `.env`로 복사합니다. 로컬 DB는 `127.0.0.1:5433`, 사용자·DB 이름은 `cctv`, 비밀번호는 `cctv_local`입니다. 이 값은 개발용이며 배포 환경에 사용하지 않습니다. `.env`에는 실제 영상 버킷, AWS 자격 증명, Gemini API 키, Modal 토큰을 채웁니다. 가중치 버킷·객체 키·SHA256은 별도로 Modal `cctv-s3` Secret에 설정합니다.

```bash
docker compose -f docker-compose.local.yml up -d
cp .env.local.example .env
set -a; source .env; set +a
uv run --locked alembic upgrade head
```

API와 작업 프로세스를 각각 실행한 뒤 Streamlit에서 영상을 업로드하거나 E2E 스크립트를 사용합니다. Modal SDK 설치와 앱 배포는 [Modal 안내](../../deploy/modal/README.md)를 따릅니다.

```bash
set -a; source .env; set +a
uv run --no-sync uvicorn services.backend.app:create_app --factory --reload
```

다른 터미널에서 동일한 `.env`를 읽어 `uv run --no-sync python -m services.backend.run_worker`를 실행합니다. 화면 확인은 `uv run --no-sync streamlit run apps/streamlit/app.py`로 진행합니다. 백엔드와 Streamlit에는 같은 `APP_API_KEY`를 설정합니다. API 서버 시작 전에 마이그레이션을 실행해야 합니다. 실제 샘플 영상의 전체 흐름은 [Compose E2E 안내](../../deploy/compose/README.md#기동과-확인)의 `scripts.smoke_modal_gemini`로 확인합니다.

## Modal 작업 흐름

별도 작업 프로세스가 queued run을 `spawn()`으로 Modal에 제출하고 `modal_call_id`를 DB에 기록합니다. Modal 함수는 영상 버킷의 원본과 별도 가중치 버킷의 모델을 읽어 추론하고 clip·frame·event/final manifest를 영상 버킷의 `output_prefix`에 저장합니다. 작업 프로세스는 완료 응답과 S3 SHA256을 검증한 뒤 후보를 DB에 등록하고 Gemini 후처리를 진행합니다.

manifest와 미디어는 할당된 attempt의 `output_prefix` 아래에 저장해야 합니다. DB에는 실제 객체 SHA256을 검증한 뒤 등록합니다. 프레임에는 `source_time_seconds`가 필요합니다. BE는 임의 HTTPS URL을 읽지 않습니다. Gemini에 보내는 전체 미디어 용량은 기본 18 MiB입니다. 이전 내부 worker API는 호환을 위해 남아 있지만 기본 Modal 실행 경로에서는 호출하지 않습니다.

## 현재 제한

- Modal GPU 함수는 코드로 연결했지만 실제 계정의 GPU·S3 통합은 아직 실행 검증 전입니다. 프로필은 `ANALYSIS_PROFILE_ID` 하나만 허용합니다.
- 제출 직후 프로세스 중단 시 call ID 회수, 장기 운영용 동시성 제어, 접근 권한 분리는 후속 작업입니다.
- RAG 문서 원문이 없으며 Gemini 입력 영상의 외부 전송·보관 정책은 배포 전 결정해야 합니다.
