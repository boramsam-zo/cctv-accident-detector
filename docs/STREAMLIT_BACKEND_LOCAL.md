# Streamlit–FastAPI 로컬 연동

이 문서는 기존 Streamlit 화면에 FastAPI를 연결한 로컬 개발 절차를 기록한다. Streamlit 담당 팀원의 `apps/streamlit/README.md`는 수정하지 않는다.

## 실행 모드

- `BACKEND_API_URL`과 `APP_API_KEY`를 설정하면 Streamlit 서버가 FastAPI 공개 API를 호출한다.
- 두 값이 없으면 기존 가상 응답 데모 화면을 사용한다. API 모드에서 연결이 실패하면 오류를 표시한다.
- `.env`는 앱에서 자동으로 읽지 않는다. 각 셸에서 `set -a; source .env; set +a`로 불러온다.

Python 3.13과 uv로 `uv sync --locked --group dev`를 실행한다. PostgreSQL·S3 테스트 서버·버킷·마이그레이션·FastAPI 실행 순서는 [백엔드 안내](../services/backend/README.md#로컬-postgresql-및-s3-테스트-서버)에 있다. 같은 환경 변수를 읽은 별도 셸에서 화면을 실행한다.

```bash
uv run --locked --group dev streamlit run apps/streamlit/app.py --server.address 127.0.0.1
```

## 연결된 공개 API

| 사용자 동작 | FastAPI 요청 |
| --- | --- |
| MP4 접수 | `POST /api/v1/videos` |
| 접수·작업 목록 복원 | `GET /api/v1/videos`, `GET /api/v1/jobs` |
| 영상 선택·분석 시작 | `GET /api/v1/analysis-profiles`, `POST /api/v1/jobs` |
| 처리 상태 확인 | `GET /api/v1/jobs/{job_id}` |
| 원본·후보 clip·frame 재생 | `GET /api/v1/assets/{asset_id}/url` |
| 검토 저장·조회 | `POST/GET /api/v1/events/{event_id}/reviews` |
| 완료 작업 재분석 | `POST /api/v1/jobs/{job_id}/runs` |

처리 중에는 5초 간격으로 상태를 조회하고 terminal 상태에서 자동 조회를 중단한다. Runpod worker가 없으면 새 작업은 `queued`에 머문다. 후보·검토 화면은 worker가 후보 이벤트를 등록한 뒤 확인할 수 있다. RAG 문서 검색은 아직 연결되지 않았다.
