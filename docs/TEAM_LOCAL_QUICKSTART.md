# develop 팀 로컬 실행

Docker Desktop의 Linux 컨테이너와 Git만 설치하면 됩니다. Python, uv, ffmpeg, CUDA,
Modal SDK는 이미지 안에 설치됩니다. GPU는 원격 Modal을 사용하므로 로컬 GPU가 필요 없습니다.
실제 영상은 업로드 MP4로 분석하며, 현재 추론 길이 제한은 120초입니다.

이 안내와 관련 파일이 develop에 병합된 뒤 저장소 루트에서 시작합니다.

```powershell
git switch develop
git pull --ff-only
```

## 1. 클라우드 계정 없이 화면부터 확인

```powershell
docker compose -f deploy/compose/compose.demo.yaml up --build -d
```

http://localhost:8501 에서 업로드 화면과 가상 분석 상태를 확인합니다.
실제 추론·문서 검색·DB 저장은 수행하지 않고 사람 검토도 세션에만 저장합니다.
화면 코드는 마운트되어 수정 후 새로고침하면 반영됩니다. .env 설정은 필요 없습니다.
실제 모드와 같은 8501 포트를 사용하므로 모드를 바꿀 때 먼저 데모를 종료합니다.

```powershell
docker compose -f deploy/compose/compose.demo.yaml down
```

## 2. 실제 영상부터 기관별 보고서까지 실행

처음 한 번 .env를 만들고 필요한 값을 채웁니다. 이미 .env가 있으면 덮어쓰지 않습니다.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.compose.example .env }
```

반드시 입력하거나 확인할 값:

- `S3_BUCKET`: 팀이 사용하는 영상·분석 근거 버킷.
- `S3_KEY_PREFIX=dev/본인이름/`: 팀원마다 고유한 경로. 해당 경로 접근 권한도 필요합니다.
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: 컨테이너가 S3에 접근할 개발용 자격 증명.
  임시 자격 증명이면 `AWS_SESSION_TOKEN`도 입력합니다. 호스트의 AWS profile은 컨테이너에 자동 전달되지 않습니다.
- `GEMINI_API_KEY`: 영상 설명·질의 임베딩·최종 보고서 생성에 사용하는 키.
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`: 배포된 팀 Modal 앱을 호출할 자격 증명.
- `POSTGRES_PASSWORD`, `APP_API_KEY`: 예시에는 로컬 실행용 기본값이 있습니다.
  DB 비밀번호에는 URL 예약 문자 `@ : / ? # %`를 사용하지 않습니다.

팀의 배포 설정과 맞출 값:

```dotenv
AWS_REGION=ap-northeast-2
S3_ENDPOINT_URL=
MODAL_ENVIRONMENT=dev
MODAL_APP_NAME=cctv-accident-inference
MODAL_FUNCTION_NAME=analyze_video_job
ANALYSIS_PROFILE_ID=received-yolo-x3ds-v1
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_MODELS=
RAG_ENABLED=true
RAG_STORE=postgres
RAG_EMBEDDING_MODEL=gemini-embedding-001
RAG_EMBEDDING_DIMENSIONS=768
RAG_TOP_K=8
RAG_MIN_SIMILARITY=0.35
MAX_UPLOAD_BYTES=104857600
MAX_GEMINI_CLIP_BYTES=18874368
MAX_MODEL_WEIGHT_BYTES=536870912
```

`GEMINI_MODEL`은 팀 계정에서 실제 사용 가능한 모델로 설정합니다. `GEMINI_MODELS`를
비워두면 기본 모델 하나만 화면에 표시합니다. 여러 모델을 허용하려면 쉼표로 나열합니다.
Compose의 DB URL과 UI의 백엔드 주소는 서비스 내부 이름으로 자동 설정됩니다.
예시 기본 모델은 2026-10-04의 정상 장면·사고 장면 E2E에 사용한 `gemini-3.5-flash-lite`입니다.
같은 날 `gemini-3.6-flash`에서는 일시적 503 과부하가 발생했습니다. 모델별 계정 권한과 한도는 별도 확인합니다.
컨테이너에서 `DATABASE_URL=localhost...` 또는 `BACKEND_API_URL=localhost...`를 별도로 설정하지 않습니다.
`.env`는 Compose가 읽어 필요한 값만 컨테이너에 전달하므로 셸마다 환경을 불러올 필요가 없습니다.

### RAG 최초 준비

팀에서 생성·검증한 `embeddings.json`을 받아 **`data/rag/embeddings.json`**에 둡니다.
이 파일은 Git에 포함되지 않으므로 develop을 받는 것만으로는 준비되지 않습니다.
반드시 같은 브랜치의 `chunks.jsonl`에 대응하는 768차원 임베딩 파일을 사용합니다.
시작 스크립트가 문서 해시·모델·차원을 확인하고 PostgreSQL에 적재합니다.
이미 호환되는 코퍼스가 로컬 DB에 있으면 파일 없이 재사용할 수 있습니다.

공유 파일이 없으면 다음 명령으로 직접 생성할 수 있습니다. **이 명령은 Gemini 임베딩 API를 호출합니다.**
팀에서 한 번 만든 파일을 공유하면 팀원마다 같은 문서를 재생성할 필요가 없습니다.

```powershell
docker compose --env-file .env -f deploy/compose/compose.yaml --profile setup run --build --rm --no-deps rag-index
```

### 한 명령으로 실행

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1
```

이 프로세스에만 실행 정책 옵션을 적용합니다. 스크립트는 .env 필수값 확인 → 이미지 빌드 →
DB 실행·상태 확인 → Alembic migration → RAG 적재·준비 확인 → API·worker·두 화면 실행을 처리합니다.
임베딩 파일과 기존 코퍼스가 모두 없으면 오류로 멈추며 임베딩 API를 자동 호출하지 않습니다.
worker가 시작되면 기존 대기 작업이 처리될 수 있고, 새 분석을 요청하면 실제 S3·Modal·Gemini를 사용합니다.

- 사용자 화면: http://localhost:8501
- E2E 화면: http://localhost:8502
- API 문서: http://localhost:8000/docs

설정만 검사하고 컨테이너를 시작하지 않으려면:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -ValidateOnly
```

이 검사는 필수값·Compose 문법만 확인합니다. 외부 자격 증명의 유효성, 모델 사용 권한,
S3 권한과 GPU 함수 배포 여부는 실제 서비스 호출 전까지 검증하지 않습니다.

## 3. 팀 관리자가 최초 한 번 준비할 항목

- Modal의 위 앱·함수를 dev 환경에 배포하고 팀원이 해당 workspace를 호출하도록 설정.
- Modal `cctv-s3` Secret에 영상 버킷 읽기·근거 쓰기 권한과 다음 기본 가중치 설정을 등록:

```dotenv
MODEL_WEIGHTS_S3_BUCKET=<가중치 버킷>
X3D_WEIGHTS_S3_KEY=<X3D-S 가중치 객체 키>
YOLO_WEIGHTS_S3_KEY=<YOLO 가중치 객체 키>
X3D_WEIGHTS_SHA256=<SHA256>
YOLO_WEIGHTS_SHA256=<SHA256>
```

이 값은 팀원의 로컬 .env에 넣는 것만으로 Modal 함수에 전달되지 않습니다.
기본 모델을 쓰면 팀원마다 가중치를 다운로드하거나 GPU 함수를 배포할 필요가 없습니다.
추가 모델 실험은 E2E 화면의 가중치 프로필 등록으로 진행합니다.

- 팀원별 S3 `dev/이름/` 경로에 필요한 읽기·쓰기 권한 부여.
- 사용 가능한 Gemini 모델·API 키와 검증된 RAG 임베딩 파일 제공.
- 짧은 테스트 MP4 제공. 영상과 가중치는 Git에 포함되지 않습니다.

## 4. 작업 중 반복 실행

develop은 공통 기준 브랜치로 유지하고 실제 수정은 작업 브랜치에서 진행합니다.

```powershell
git switch develop
git pull --ff-only
git switch -c feat/작업이름
```

로컬 DB·`.env`·테스트 영상·가중치·임베딩 파일은 브랜치를 바꿔도 자동으로 준비되지 않습니다.
팀에서 받은 자격 증명과 `embeddings.json`, 짧은 테스트 MP4를 먼저 준비하세요.
`.env`의 `S3_KEY_PREFIX`에는 자신의 이름을 사용합니다.

화면은 소스가 마운트되어 새로고침으로 반영됩니다. API는 `--reload`로 자동 재시작합니다.
worker 코드 변경은 다음 명령으로 재시작합니다.

```powershell
docker compose --env-file .env -f deploy/compose/compose.yaml restart worker
```

의존성·Dockerfile·환경 변수 변경 시 시작 스크립트를 다시 실행합니다.
`src/accident_vision` 변경은 원격 Modal 이미지에 포함되므로 GPU 함수를 다시 배포해야 합니다.
로컬 UI 재시작만으로는 원격 GPU 코드가 바뀌지 않습니다.

VLM·RAG 작업은 `services/backend/gemini_vlm.py`, `scene_facts.py`, `rag.py`를 수정합니다.
현재 기본 출력 계약은 `scene-facts-v2`이며 사고 여부와 8개 관찰 항목을 `present / absent / unknown`으로 구분합니다.
스키마나 의미가 바뀌면 [공통 계약](contracts/service_contract.md)과 관련 테스트도 함께 수정합니다.
API·worker 재시작 후 E2E 화면의 기본 프롬프트가 `scene-facts-v2`인지 확인하세요.
실제 JSON·클립 정답 비교 방법은 [VLM 검증 안내](VLM_FACTS_VALIDATION.md)를 따릅니다.

Python을 호스트에 설치하지 않고 자동 테스트를 실행하려면, 실행 중인 개발 backend의 Python과 소스를 사용합니다.
테스트 디렉터리와 데모 계약 자료는 아래 명령에서 마운트합니다.

```powershell
docker compose --env-file .env -f deploy/compose/compose.yaml -f deploy/compose/compose.dev.yaml run --rm --no-deps -v "${PWD}/tests:/app/tests:ro" -v "${PWD}/docs/contracts:/app/docs/contracts:ro" backend python -m pytest tests/unit tests/integration tests/smoke -q -o cache_dir=/tmp/pytest-cache
```

이 자동 테스트는 외부 서비스를 모의 처리합니다. 실제 서비스 E2E는 8502 화면에서 별도로 실행합니다.
기능 확인 후 작업 브랜치를 커밋·푸시하고 develop 대상 PR로 공유합니다.

```powershell
git add 수정한파일
git commit -m "작업 내용"
git push -u origin HEAD
```

로그와 종료:

```powershell
docker compose --env-file .env -f deploy/compose/compose.yaml logs --tail=100 backend worker
docker compose --env-file .env -f deploy/compose/compose.yaml --profile test down
```

DB는 Docker 볼륨에 보존됩니다. `down -v`는 로컬 DB를 삭제하므로 초기화할 때만 사용합니다.
MLflow와 Terraform은 기본 로컬 테스트에 필요하지 않습니다.

## 5. 성공 기준

E2E 화면에서 `검색 준비 완료 · postgres · 275개 청크 · 768차원`을 확인합니다.
MP4 업로드 후 작업이 completed가 되고 객체·사고·근거·VLM·RAG·보고서 단계가 모두 완료되어야 합니다.
사고 후보가 있으면 원본/객체 표시 클립, 장면 설명, 문서 인용과 기관별 안내를 확인합니다.
사고 후보가 없는 영상은 VLM·RAG·보고서를 실행하지 않으므로 전체 경로 확인에는 사고 후보가 나오는 샘플이 필요합니다.
새 검토를 저장하고 새로고침 후 유지되는지도 확인합니다.

## 6. 모델 연결 장애와 재검증

Gemini의 503 과부하 응답은 `partial` 및 VLM 실패로 기록됩니다. E2E 화면에서 VLM만 재시도하면
기존 Modal 후보·근거 파일을 재사용합니다. 계약 검증 실패도 실패로 남기며 임의로 값을 보정하지 않습니다.
과부하가 반복되면 `GEMINI_MODELS`에 팀 계정에서 사용 가능한 모델을 등록하고,
E2E 화면에서 해당 모델을 선택해 새 분석을 실행합니다. 모델 변경을 자동으로 수행하지 않습니다.
계정의 모델 사용 가능 여부와 API 한도는 팀 관리자에게 확인하세요.
