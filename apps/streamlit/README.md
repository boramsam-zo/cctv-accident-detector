# Streamlit 화면

기본 실행은 FastAPI에 연결합니다. `BACKEND_API_URL`과 `APP_API_KEY`가 필요하며, 연결되지 않으면 화면에 오류를 표시합니다. `APP_MODE=demo`를 명시한 경우에만 `docs/contracts/demo-analysis-cases-v0.2.json`의 가상 응답을 사용합니다.

## 실행

프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
uv venv .venv --python 3.13
.\.venv\Scripts\Activate.ps1
uv pip install -r apps/streamlit/requirements.txt
python -m streamlit run apps/streamlit/app.py
```

Git Bash에서는 가상 환경을 다음처럼 활성화합니다.

```bash
source .venv/Scripts/activate
```

실제 흐름은 백엔드와 함께 실행해야 합니다. Compose 실행 방법은 [개발용 Compose 안내](../../deploy/compose/README.md)를 참고하세요.

## 현재 범위

- 로컬 영상 최대 5개 선택, 접수 목록과 개별 미리보기
- Stitch 관제 화면 형태의 영상 카드 목록과 선택 영상 분석 화면 이동
- 카드 전체가 하나의 클릭 영역: 8MB 이하 영상은 마우스를 올리면 8초 미리보기, 카드 어디를 클릭해도 분석 화면으로 이동
- 모바일은 첫 탭에 미리보기 재생, 재생 중 다시 탭하면 분석 화면으로 이동
- 영상 카드를 열 때 해당 영상의 독립 분석 작업 생성 흐름
- 영상 접수와 분석 요청을 분리한 사용자 흐름
- API 계약의 작업 상태, coverage, 단계 상태, 후보 상세 표시
- VLM/RAG/보고서 상태 표시
- 세션 내 사람 검토 저장
- 가상 응답 8종 전환

실제 모드는 영상을 FastAPI로 업로드하고 작업·검토 결과를 PostgreSQL에 저장합니다. 데모 모드의 영상과 검토 결과는 브라우저 세션에서만 유지됩니다.

## 연결 API

화면은 다음 FastAPI를 사용합니다.

1. `POST /api/v1/videos`
2. `POST /api/v1/jobs`
3. `GET /api/v1/jobs`와 `GET /api/v1/jobs/{job_id}`
4. `GET /api/v1/assets/{asset_id}/url`
5. `POST /api/v1/events/{event_id}/reviews`

업로드와 작업 생성 요청은 사용자 동작별 `Idempotency-Key`를 유지해야 하며, terminal 상태가 되면
자동 상태 조회를 중단해야 합니다.

## E2E 수치 테스트 화면

실제 백엔드의 기존 업로드·작업 생성·조회 함수를 사용해 S3, Modal, Gemini VLM 흐름을 확인하는 최소 화면은 다음 명령으로 실행합니다.

```bash
docker compose --env-file .env -f deploy/compose/compose.yaml --profile test up --build -d test-ui
```

브라우저에서 `http://127.0.0.1:8502`를 엽니다. 모델 프로필과 MP4 파일을 선택하면 처리 구간 수, 사고 후보 수, 최대 후보 점수, VLM 완료·관찰 수, RAG 입력 수, 오류 수를 표시합니다. 작업이 끝나면 VLM JSON도 펼쳐 볼 수 있습니다.

Gemini 모델 목록은 코드에 고정하지 않고 `.env`의 쉼표 구분 `GEMINI_MODELS`에서 읽습니다. `GEMINI_MODEL`은 기본 선택값입니다. 화면의 프롬프트는 작업별로 저장되며 기존 JSON 출력·판정 규칙 앞에 추가하거나 전체 지시를 교체할 수 있습니다. 두 방식 모두 이벤트 시각과 객체 탐지 근거는 자동으로 전달됩니다.

`VLM 프롬프트` 입력칸에는 현재 기본 분석 프롬프트 전체가 미리 채워집니다. 기본 적용 방식은 `전체 지시 교체`이며 화면에서 수정한 내용이 작업 설정에 그대로 저장됩니다. 분석 완료 후 `VLM 입력·출력 확인`에서 Gemini에 실제 전송된 최종 프롬프트·모델·근거 asset ID와 검증된 원본 구조화 출력을 후보별로 나란히 확인할 수 있습니다.

사고 후보가 생성되면 `사고 후보 클립`에서 후보 시각을 중심으로 Modal이 만든 근거 MP4를 바로 재생할 수 있습니다. 화면은 백엔드에서 짧게 유효한 S3 서명 URL을 발급받아 사용합니다.

`선택 모델 연결 확인`은 선택한 모델에 최소 텍스트 요청을 보내 현재 API 키, 모델 접근 권한, 할당량과 응답 지연을 확인합니다. 이 검사는 영상 입력과 구조화 출력 전체를 검증하지 않습니다. 실제 영상 분석 후 표시되는 `실제 영상 VLM 응답 정상/실패`가 최종 E2E 확인 결과입니다.

`모델·가중치 프로필 등록`에서 사고 모델과 객체 모델의 `.pt` 또는 `.pth` 파일을 올리면 백엔드가 SHA-256을 계산해 영상 버킷의 `model-profiles/{profile_id}/` 경로에 저장하고 DB에 프로필을 등록합니다. 등록 직후 모델/가중치 선택 목록에 표시되며, 작업에는 S3 키와 해시가 포함된 프로필 스냅샷이 저장됩니다.

여러 모델과 가중치를 선택할 수 있게 확장하는 방식은 [Modal 모델 프로필 설계](../../docs/MODAL_MODEL_PROFILES.md)를 참고합니다.
