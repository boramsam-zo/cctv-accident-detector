# CCTV Accident Detector

영상에서 객체와 충돌 의심 구간을 분석하는 프로젝트입니다.

현재는 기본 폴더 구조와 팀 개발용 PRD·공통 계약을 준비했습니다. FastAPI 백엔드의 로컬 개발 구현도 있습니다. GPU 모델 실행과 배포는 다음 단계입니다. 구조와 구현 순서는 [프로젝트 폴더 구조](docs/PROJECT_FOLDER_STRUCTURE.md)를 참고하세요.

## 로컬 개발 환경 (uv)

Python 3.11과 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 설치한 뒤 저장소 루트에서 실행합니다. `uv.lock`을 Git에 함께 올려 모든 팀원이 같은 Python 패키지 버전을 설치합니다.

```bash
git switch develop
git pull --ff-only
uv sync --locked
uv run --locked pytest -q
```

`uv sync`가 `.python-version`에 맞는 Python과 `.venv`를 준비합니다. 통합 테스트는 가짜 S3·Pod·Gemini를 사용하므로 클라우드 자격증명 없이 실행됩니다. API를 직접 실행하려면 `ffprobe`와 실제 DB/S3/Gemini 설정이 필요합니다. 설정과 실행 명령은 [백엔드 README](services/backend/README.md)를 참고하세요.

## 팀원 시작 안내

1. [전체 PRD](PROJECT_BRIEF.md): 목표·범위·아키텍처.
2. [공통 API·데이터 계약](docs/contracts/service_contract.md)과 [HTTP API 상세 명세](docs/contracts/api-spec-v0.2.md): 작업 상태·요청/응답·오류·검토 저장.
3. [담당 역할 문서](docs/roles/README.md): FE·BE·모델·VLM/RAG·인프라·QA.
4. [구현 계획](IMPLEMENTATION_PLAN.md)과 [현재 상태](docs/current_status.md).

X3D-S가 사고 후보 구간을 찾고 YOLO11s가 해당 장면의 객체 정보를 제공합니다. 수신 YOLO 가중치는 7개 클래스이며 Dynamic의 라벨 정의는 확인 중입니다. [수신 모델 확인](docs/contracts/received-model-metadata-v0.2.json)은 정적 검사 결과이고 실제 추론 성능 검증은 아닙니다.

## 현재 폴더 안내

| 폴더 | 추천 파일 |
| --- | --- |
| `src/accident_vision/` | 객체 탐지·충돌 추론, 영상 파이프라인, 입력·출력 스키마 |
| `configs/models/` | 모델별 추론 설정 YAML |
| `models/` | 가중치 버전 목록과 SHA256 목록 |
| `training/object_detection/` | YOLO11s 학습 설정·노트북·평가 기록 |
| `training/collision_detection/` | X3D-S 학습 설정·노트북·평가 기록 |
| `tests/smoke/` | 샘플 영상 추론 실행 확인 테스트 |
| `docs/` | 프로젝트 구조·추론 계약·결정 기록 |

각 폴더의 README에 파일별 추천 내용과 추가 시점을 적었습니다.
