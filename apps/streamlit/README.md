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
