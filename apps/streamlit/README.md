# Streamlit 데모 화면

API 구현 전 화면 흐름을 검토하기 위한 프론트엔드입니다. 저장소의
`docs/contracts/demo-analysis-cases-v0.2.json`을 읽어 대기, 분석 중, 후보 없음, 부분 완료,
설명 생성 중, 문서 근거 부족, VLM 실패, 전체 실패 상태를 표시합니다.

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

현재 화면은 데모 데이터만 사용합니다. 영상은 브라우저 세션에서만 미리보기하며 서버, S3 또는
Runpod으로 전송하지 않습니다. 검토 결과도 DB가 아니라 현재 Streamlit 세션에만 보관됩니다.

## 다음 연결점

FastAPI 구현 후 화면의 데이터 공급을 다음 API로 교체합니다.

1. `POST /api/v1/videos`
2. `POST /api/v1/jobs`
3. `GET /api/v1/jobs`와 `GET /api/v1/jobs/{job_id}`
4. `GET /api/v1/assets/{asset_id}/url`
5. `POST /api/v1/events/{event_id}/reviews`

업로드와 작업 생성 요청은 사용자 동작별 `Idempotency-Key`를 유지해야 하며, terminal 상태가 되면
자동 상태 조회를 중단해야 합니다.
