# EC2 개발용 Docker Compose

목표 흐름은 Streamlit 영상 업로드 → FastAPI의 영상 버킷 저장·PostgreSQL 작업 등록 → Modal GPU의 X3D-S/YOLO11s 추론 → 같은 영상 버킷에 clip·frame·manifest 저장 → EC2 worker의 Gemini 호출 → 구조화 JSON 저장·화면 조회입니다. RAG 검색과 최종 LLM 보고서는 이번 구성에 포함하지 않습니다.

| 서비스 | 역할 | GPU |
| --- | --- | --- |
| `postgres` | 영상·작업·후보·Gemini 결과 상태 저장 | 없음 |
| `migrate` | DB 시작 후 Alembic 스키마 적용, 완료 시 종료 | 없음 |
| `backend` | Streamlit API, 업로드, S3/DB 조회 | 없음 |
| `worker` | Modal 작업 제출·결과 확인, S3 근거 검증, Gemini JSON 생성 | 없음 |
| `streamlit` | 업로드·상태·후보·Gemini 결과 화면 | 없음 |

Modal GPU 함수는 Compose 서비스가 아닙니다. [Modal 안내](../modal/README.md)에 따라 별도로 `dev` 환경에 배포하고, `cctv-s3` Secret에는 영상·가중치 버킷을 읽고 쓸 권한을 설정합니다. 영상과 가중치는 서로 다른 버킷입니다. 호스트에 Modal CLI가 없어도 앱 이미지의 CLI로 배포할 수 있습니다. `worker`의 Modal 토큰은 EC2의 `.env`에서 주입합니다. EC2 IAM 역할은 영상 버킷의 개발 prefix에만 접근합니다.

## 환경 변수

저장소 루트의 `.env.example`을 `.env`로 복사해 다음 값을 채웁니다. `.env`와 실제 자격 증명은 Git에 올리지 않습니다.

```dotenv
POSTGRES_PASSWORD=<URL에 사용할 수 있는 강한 개발용 비밀번호>
APP_API_KEY=<화면과 API가 공유할 임의의 긴 토큰>
S3_BUCKET=<영상 업로드 및 근거 저장 버킷 이름>
S3_KEY_PREFIX=dev/ec2/
AWS_REGION=ap-northeast-2
S3_ENDPOINT_URL=
GEMINI_API_KEY=<Gemini API 키>
MODAL_TOKEN_ID=<Modal 토큰 ID>
MODAL_TOKEN_SECRET=<Modal 토큰 Secret>
MODAL_ENVIRONMENT=dev
MODAL_APP_NAME=cctv-accident-inference
MODAL_FUNCTION_NAME=analyze_video_job
```

`S3_KEY_PREFIX`는 Terraform의 `video_key_prefix`와 같아야 합니다. `POSTGRES_PASSWORD`는 이 개발용 Compose에서 DB URL에 직접 들어가므로 URL 예약 문자(`@`, `:`, `/`, `?`, `#`, `%`)를 피하세요. 컨테이너의 `DATABASE_URL`과 Streamlit의 `BACKEND_API_URL`은 Compose가 내부 DNS 이름으로 설정합니다. EC2에서는 인스턴스 역할을 사용하므로 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`은 설정하지 않습니다. 가중치 버킷·객체 키·해시는 EC2 `.env`가 아니라 Modal `cctv-s3` Secret에 설정합니다.

Compose의 Streamlit은 `APP_MODE=live`로 실행합니다. 이때 실제 FastAPI 연결 설정이 없으면 오류를 표시하고 시작을 중단하며, 데모 JSON을 이미지에 포함하거나 읽지 않습니다. 백엔드와 worker는 기본 구성에서 실제 S3·Modal·Gemini 클라이언트를 사용합니다.

## 기동과 확인

EC2에 SSM으로 접속한 뒤 이 파일이 들어 있는 브랜치를 체크아웃합니다. EC2의 Docker·Compose 설치는 [Terraform 안내](../terraform/dev-ec2/README.md)를 따릅니다. Docker 그룹을 적용하려면 설치 후 새 SSM 세션으로 접속하세요.

```bash
cp .env.example .env
# .env에 위 값 입력
docker compose --env-file .env -f deploy/compose/compose.yaml config --quiet
docker compose --env-file .env -f deploy/compose/compose.yaml up --build -d
docker compose --env-file .env -f deploy/compose/compose.yaml ps
docker compose --env-file .env -f deploy/compose/compose.yaml logs -f backend worker
```

`migrate`가 0으로 종료되고 `backend`가 healthy이면 `http://127.0.0.1:8000/health`를 확인합니다. 외부에서는 기본적으로 SSM 포트 포워딩으로 Streamlit `8501`에 접속합니다. Terraform에서 `streamlit_cidrs`를 지정한 경우에만 해당 CIDR에서 EC2의 8501 포트에 직접 연결할 수 있습니다. 8000 포트는 호스트 루프백에만 게시하고, PostgreSQL 포트는 게시하지 않습니다.

Streamlit에서 영상을 업로드하고 분석을 요청한 뒤, `GET /api/v1/jobs/{job_id}`의 `candidates[].rag_input`에 Gemini 구조화 JSON이 저장됐는지 확인합니다. 후보가 없는 영상은 Gemini를 호출하지 않습니다. 단계 상태와 실패 원인은 같은 작업 응답 및 `worker` 로그에서 확인합니다. [VLM→RAG JSON 계약](../../docs/contracts/vlm-rag-input-v1.md)을 참고하세요.

저장소 루트의 `.local/clip.mp4`를 사용해 전체 API 경로를 자동 확인하려면 **컨테이너가 실행되는 호스트의 터미널**에서 다음을 실행합니다. `BACKEND_API_URL`과 `APP_API_KEY`는 스크립트를 실행하는 셸에만 로드합니다. 이 스크립트는 영상을 새로 업로드하고 새 분석 작업을 생성하므로 실행할 때마다 S3·DB에 새 데이터가 남습니다.

```bash
set -a
source .env
set +a
.venv/bin/python -m scripts.smoke_modal_gemini .local/clip.mp4
```

완료 시 검증된 `gemini_json`을 출력합니다. `candidate_count=0`이면 실제 영상에서 충돌 의심 후보를 찾지 못한 것이므로 Gemini 검증까지 진행되지 않습니다. `failed`/`partial` 또는 시간 초과 시 `docker compose --env-file .env -f deploy/compose/compose.yaml logs --tail=100 worker backend`로 해당 단계를 확인합니다.

현재 Docker 이미지는 앱 의존성을 `uv.lock`으로 설치하고 Modal SDK를 `deploy/modal/requirements.txt`로 별도 설치합니다. 실제 EC2·Modal·S3·Gemini를 함께 실행한 검증은 아직 하지 않았습니다. EC2 디스크의 PostgreSQL 볼륨은 인스턴스를 교체하거나 `docker compose down -v`를 실행하면 잃을 수 있으므로 필요한 데이터는 별도로 백업해야 합니다.
