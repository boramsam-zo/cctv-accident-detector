# Streamlit–FastAPI 로컬 연동

이 문서는 Streamlit 화면과 FastAPI의 로컬 연결 절차를 기록한다. 화면 자체의 실행 범위는 [`apps/streamlit/README.md`](../apps/streamlit/README.md)를 따른다.

## 실행 모드

- 기본 `APP_MODE=live`에서 `BACKEND_API_URL`과 `APP_API_KEY`가 필요하다. 연결이 실패하면 오류를 표시하고 데모 응답으로 전환하지 않는다.
- 화면 상태만 검토할 때 `APP_MODE=demo`를 명시하면 가상 응답을 사용한다.
- `.env`는 앱에서 자동으로 읽지 않는다. 각 셸에서 `set -a; source .env; set +a`로 불러온다.

Python 3.13과 uv로 `uv sync --locked --group dev`를 실행한다. PostgreSQL·실제 AWS S3·마이그레이션·FastAPI 실행 순서는 [백엔드 안내](../services/backend/README.md#로컬-postgresql과-실제-s3-연결)에 있다. 같은 환경 변수를 읽은 별도 셸에서 화면을 실행한다.

```bash
uv run --no-sync streamlit run apps/streamlit/app.py --server.address 127.0.0.1
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

처리 중에는 5초 간격으로 상태를 조회하고 terminal 상태에서 자동 조회를 중단한다. Modal 앱과 별도 백엔드 작업 프로세스가 실행되지 않으면 새 작업은 `queued`에 머문다. 실제 Modal 통합 시험에는 원격 함수가 접근할 수 있는 AWS S3가 필요하다. 후보·검토 화면은 Modal 결과가 DB에 등록된 뒤 확인할 수 있다. RAG 문서 검색은 아직 연결되지 않았다.
