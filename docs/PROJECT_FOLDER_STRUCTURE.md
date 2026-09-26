# 프로젝트 폴더 구조

상태: 제안
적용 범위: 팀 공용 모노레포 초기 구성

## 전체 처리 구조

```text
Streamlit → EC2 백엔드 → S3 원본 영상 저장
→ Modal 비동기 GPU 추론 (YOLO11s 객체 탐지, X3D-S 충돌 의심 탐지)
→ S3 분석 영상·대표 프레임·JSON 저장
→ EC2 백엔드에서 외부 VLM API 호출 → RAG 검색
→ DB 작업 상태·리포트 저장 → Streamlit 결과 표시
```

초기 구성에서는 SQS와 DLQ를 사용하지 않습니다. Modal `spawn()`과 `call_id`로 비동기 GPU 작업을 관리하고 DB에 작업 상태를 영속 저장합니다.

## 초기 배포 단위

```text
EC2
├── Streamlit
└── FastAPI 백엔드

Modal
└── GPU 추론 앱

AWS
├── S3
├── DynamoDB 또는 PostgreSQL
└── CloudWatch
```

처음에는 Streamlit과 백엔드를 같은 EC2 인스턴스에서 실행합니다. Streamlit은 백엔드 API를 통해서만 분석을 요청하며, GPU 추론은 Modal에서 실행합니다. 프로세스 실행 방식과 공개 접속 구성은 배포 단계에서 정합니다.

## 현재 생성된 구조

```text
.
├── README.md
├── src/accident_vision/
│   ├── __init__.py
│   └── README.md
├── configs/models/
│   └── README.md
├── models/
│   └── README.md
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

추천 파일과 세부 폴더는 아직 생성하지 않았습니다. 기존 모델 코드, 테스트, 노트북, 산출물이 인계되면 보존하면서 해당 위치로 옮깁니다.

## 폴더 책임

| 위치 | 책임 |
| --- | --- |
| `src/accident_vision/` | 로컬과 Modal이 함께 사용하는 객체 탐지, 충돌 의심 탐지, 영상 파이프라인 및 추론 계약 |
| `configs/models/` | 모델별 설정 |
| `models/` | 가중치 버전과 SHA256 검증 정보 |
| `training/object_detection/` | YOLO11s 학습 및 평가 자료 |
| `training/collision_detection/` | X3D-S와 기존 충돌 모델 학습 및 평가 자료 |
| `tests/smoke/` | 샘플 영상 기반 공통 추론 실행 확인 |
| `docs/` | API, 추론 계약, 결정 사항 및 테스트 계획 문서 |

## 폴더별 추천 파일

아래 경로는 각 폴더 README의 추천 목록입니다. 실제 파일은 모델 자산 또는 계약이 확정될 때 추가합니다.

| 폴더 | 추천 파일 | 내용 |
| --- | --- | --- |
| `src/accident_vision/` | `schemas.py` | 영상 분석 요청·탐지 결과·사고 의심 이벤트 계약 |
| `src/accident_vision/` | `detection/loader.py`, `detection/predict.py`, `detection/preprocessing.py`, `detection/visualize.py` | YOLO11s 로드·추론·전처리·시각화 |
| `src/accident_vision/` | `collision/loader.py`, `collision/predict.py`, `collision/preprocessing.py`, `collision/postprocessing.py` | X3D-S 로드·추론·클립 전처리·점수 후처리 |
| `src/accident_vision/` | `pipeline/analyze_video.py`, `pipeline/event_grouping.py`, `pipeline/result_builder.py` | 공통 영상 추론·의심 구간 묶음·결과 JSON 생성 |
| `src/accident_vision/` | `io/video_file.py`, `io/s3_video.py` | 로컬 파일·S3 영상 입력 |
| `configs/models/` | `yolo11s.yaml`, `x3d_s.yaml` | 모델별 가중치 버전·입력 형식·추론 임계값 |
| `models/` | `registry.yaml`, `checksums.sha256` | 가중치 저장 위치·버전·SHA256 검증 정보 |
| `training/object_detection/` | `configs/train.yaml`, `notebooks/train_yolo11s.ipynb`, `notebooks/evaluate_yolo11s.ipynb` | YOLO11s 학습 설정·실험·평가 |
| `training/collision_detection/` | `configs/train_x3d_s.yaml`, `notebooks/train_x3d_s.ipynb`, `notebooks/evaluate_x3d_s.ipynb` | X3D-S 학습 설정·실험·평가 |
| `tests/smoke/` | `test_local_inference.py`, `test_model_loading.py` | 샘플 영상 추론·모델 로드 확인 |
| `docs/` | `PROJECT_CONTEXT.md`, `INFERENCE_CONTRACT.md`, `API_DOCS.md`, `DECISIONS.md`, `TEST_PLAN.md` | 범위·추론 계약·API·결정 기록·검증 기준 |

대용량 가중치와 데이터 원본은 저장소에 직접 추가하지 않고 저장 위치를 문서화합니다. 학습 노트북과 Colab 전용 코드는 운영 추론 패키지에서 import하지 않습니다.

## 결정 후 생성할 폴더

| 폴더 | 생성 조건 |
| --- | --- |
| `apps/streamlit/` | 화면 담당과 API 계약 확정 |
| `services/backend/` | FastAPI와 DB 선택 확정 |
| `deploy/modal/` | Modal 계정·가중치·추론 코드 인계 완료 |
| `deploy/ec2/` | EC2 인스턴스·프로세스 실행·접속 방식 확정 |
| `rag/` | 문서 출처·임베딩·저장소 확정 |

## 초기 구현 순서

1. 모델 가중치와 설정 인계 및 SHA256 확인
2. 로컬에서 YOLO11s와 X3D-S 공통 추론 실행
3. 공통 추론 JSON 계약 확정
4. Modal에서 같은 추론 코드 실행
5. S3 입력·결과 저장 연결
6. EC2 백엔드의 분석 제출·상태 조회 구현
7. Streamlit과 백엔드 연결
8. VLM 구조화 응답 구현
9. RAG 검색과 리포트 연결
10. CloudWatch 로그와 실패 상태 검증

첫 구현은 샘플 영상 업로드·분석 방식으로 검증합니다. 실시간 CCTV 스트림 입력은 별도 범위 결정 후 추가합니다.
