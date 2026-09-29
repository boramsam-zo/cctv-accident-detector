# 프로젝트 폴더 구조

상태: Modal GPU·EC2 개발용 Compose/Terraform 코드 추가 · 실제 클라우드 검증 전
적용 범위: 팀 공용 모노레포 초기 구성

## 최신 개발 문서

[PRD](../PROJECT_BRIEF.md), [공통 계약](contracts/service_contract.md), [역할별 문서](roles/README.md)를 개발 기준으로 사용합니다. API·추론 필드는 공통 계약에서 관리합니다. 실제 구현 상태는 [README 현재 상태](../README.md#현재-상태)를 따릅니다.

## 전체 처리 구조

```text
Streamlit → EC2 백엔드 → S3 원본 영상 저장
→ 백엔드 작업 프로세스가 Modal GPU 함수를 비동기 제출
→ Modal: X3D-S 후보 구간 → 후보 장면의 YOLO11s 객체 정보
→ S3 후보 clip·대표 frame·manifest 저장
→ EC2 작업 프로세스에서 Gemini VLM 호출
→ PostgreSQL에 작업 상태·Gemini 구조화 JSON 저장 → Streamlit 결과 표시
```

초기 구성에서는 SQS와 DLQ를 사용하지 않습니다. 백엔드 작업 프로세스가 Modal의 `spawn()`으로 분석을 제출하고 `modal_call_id`를 DB에 저장합니다. 결과는 S3와 DB에 영속 저장합니다. RAG 검색과 최종 LLM 보고서는 다음 단계입니다.

## 초기 배포 단위

```text
EC2
├── PostgreSQL (Compose 볼륨)
├── FastAPI 백엔드
├── BE 작업 프로세스 (Modal 제출·회수·Gemini 후속 처리)
└── Streamlit

Modal GPU 함수
├── 영상 버킷에서 원본, 모델 버킷에서 가중치 로드
├── X3D-S·YOLO11s 오프라인 추론
└── 영상 버킷에 clip·frame·manifest 저장

AWS
├── S3 영상 버킷·모델 버킷
└── CloudWatch
```

처음에는 Streamlit과 백엔드를 같은 EC2 인스턴스에서 실행합니다. Streamlit은 백엔드 API를 통해 업로드와 분석을 요청하며, GPU 추론은 Modal에서 실행합니다. 현재 모델 코드는 파일 전체를 오프라인으로 분석합니다.

## 현재 구조와 모델·학습 기본 구조

```text
.
├── README.md
├── alembic.ini
├── docker-compose.local.yml
├── apps/streamlit/
│   ├── app.py
│   ├── backend_client.py
│   └── README.md
├── services/backend/
│   ├── app.py
│   ├── modal_service.py
│   ├── models.py
│   ├── db.py
│   └── README.md
├── migrations/
│   ├── env.py
│   └── versions/
├── src/accident_vision/
│   ├── __init__.py
│   ├── pipeline.py
│   ├── timeline.py
│   └── README.md
├── deploy/modal/
│   ├── app.py
│   ├── requirements.txt
│   └── README.md
├── deploy/compose/
│   ├── Dockerfile.app
│   ├── compose.yaml
│   └── README.md
├── deploy/terraform/dev-ec2/
│   ├── main.tf
│   ├── user_data.sh
│   └── README.md
├── scripts/
│   └── smoke_modal_gemini.py
├── training/
│   ├── object_detection/
│   │   └── README.md
│   └── collision_detection/
│       └── README.md
├── docs/
│   ├── README.md
│   └── PROJECT_FOLDER_STRUCTURE.md
└── tests/smoke/
    └── README.md
```

위 트리는 주요 파일과 학습 기본 구조를 함께 보여줍니다. Streamlit은 FastAPI 공개 API로 영상 접수·작업 조회·근거 재생·검토 저장을 수행합니다. PostgreSQL 스키마는 Alembic 마이그레이션으로 관리합니다. 모델 코드의 실제 GPU 실행은 Modal에서 검증해야 합니다. 가중치는 저장소 밖의 S3에 두고, 객체 키와 SHA256은 Modal Secret으로 전달합니다. 현재 추론 설정은 `src/accident_vision/pipeline.py`와 `timeline.py`에 있습니다.

## 폴더 책임

| 위치 | 책임 |
| --- | --- |
| `apps/streamlit/` | 사용자 화면과 FastAPI 클라이언트. Modal·S3·DB 직접 접근 없음 |
| `services/backend/` | 공개 API, Modal 제출·결과 검증, S3 영상 접근, Gemini 후속 처리 |
| `migrations/` | PostgreSQL 스키마 버전 관리 |
| `docker-compose.local.yml` | 로컬 PostgreSQL 실행 |
| `deploy/compose/` | EC2 개발용 PostgreSQL·FastAPI·worker·Streamlit 기동 |
| `deploy/terraform/dev-ec2/` | 개발용 EC2, IAM, SSM 접속, Docker·Compose 설치 |
| `src/accident_vision/` | 로컬과 Modal 함수가 함께 사용하는 객체 탐지, 충돌 의심 탐지, 영상 파이프라인 |
| `deploy/modal/` | Modal GPU 함수 배포 진입점과 S3 결과 저장 |
| `scripts/` | 업로드부터 Modal 추론·Gemini JSON까지 실제 E2E 확인 |
| `training/object_detection/` | YOLO11s 학습 및 평가 자료 |
| `training/collision_detection/` | X3D-S와 기존 충돌 모델 학습 및 평가 자료 |
| `tests/smoke/` | 샘플 영상 기반 공통 추론 실행 확인 |
| `docs/` | API, 추론 계약, 결정 사항 및 테스트 계획 문서 |

## 폴더별 추천 파일

아래 경로는 각 폴더 README의 향후 분리 추천 목록입니다. 현재 공통 추론 구현은 `src/accident_vision/pipeline.py`와 `timeline.py`에 있습니다.

| 폴더 | 추천 파일 | 내용 |
| --- | --- | --- |
| `src/accident_vision/` | `schemas.py` | 영상 분석 요청·탐지 결과·사고 의심 이벤트 계약 |
| `src/accident_vision/` | `pipeline.py`, `timeline.py` | 현재 X3D-S·YOLO11s MP4 추론과 후보 구간 묶음 |
| `src/accident_vision/` | `detection/loader.py`, `detection/predict.py`, `detection/preprocessing.py`, `detection/visualize.py` | YOLO11s 로드·추론·전처리·시각화 |
| `src/accident_vision/` | `collision/loader.py`, `collision/predict.py`, `collision/preprocessing.py`, `collision/postprocessing.py` | X3D-S 로드·추론·클립 전처리·점수 후처리 |
| `src/accident_vision/` | `pipeline/analyze_video.py`, `pipeline/event_grouping.py`, `pipeline/result_builder.py` | 공통 영상 추론·의심 구간 묶음·결과 JSON 생성 |
| `src/accident_vision/` | `io/video_file.py`, `io/s3_video.py` | 로컬 파일·S3 영상 입력 |
| `training/object_detection/` | `configs/train.yaml`, `notebooks/train_yolo11s.ipynb`, `notebooks/evaluate_yolo11s.ipynb` | YOLO11s 학습 설정·실험·평가 |
| `training/collision_detection/` | `configs/train_x3d_s.yaml`, `notebooks/train_x3d_s.ipynb`, `notebooks/evaluate_x3d_s.ipynb` | X3D-S 학습 설정·실험·평가 |
| `tests/smoke/` | `test_local_inference.py`, `test_model_loading.py` | 샘플 영상 추론·모델 로드 확인 |
| `docs/` | `contracts/service_contract.md`, `roles/`, `requirements.md`, `PROGRESS.md` | 현재 PRD의 계약·역할·요구사항·실행 기록 |

대용량 가중치와 데이터 원본은 저장소에 직접 추가하지 않고 저장 위치를 문서화합니다. 학습 노트북과 Colab 전용 코드는 운영 추론 패키지에서 import하지 않습니다.

## 결정 후 생성할 폴더

| 폴더 | 생성 조건 |
| --- | --- |
| `rag/` | 문서 출처·임베딩·저장소 확정 |

## 초기 구현 순서

1. 모델 가중치와 설정 인계 및 SHA256 확인
2. 코드·설정을 로컬에서 준비하고 승인한 GPU 환경에서 공통 추론 확인
3. 공통 계약 초안 검토·가상 응답으로 FE/BE 착수 (모델 연결과 병행 가능)
4. Modal GPU 함수에서 같은 추론 코드 실행
5. S3 입력·결과 저장 연결
6. EC2 백엔드의 분석 제출·상태 조회 구현
7. Streamlit과 백엔드 연결
8. VLM 구조화 응답 구현
9. RAG 검색과 리포트 연결
10. CloudWatch 로그와 실패 상태 검증

첫 구현은 샘플 영상 업로드·분석 방식으로 검증합니다. 실시간 CCTV 스트림 입력은 별도 범위 결정 후 추가합니다.
