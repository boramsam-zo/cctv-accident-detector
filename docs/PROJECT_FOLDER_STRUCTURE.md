# 프로젝트 폴더 구조

상태: 기본 폴더 생성 완료 · 서비스 상세는 PRD v0.2 개발 제안
적용 범위: 팀 공용 모노레포 초기 구성

## 최신 개발 문서

[PRD](../PROJECT_BRIEF.md), [공통 계약](contracts/service_contract.md), [역할별 문서](roles/README.md)를 개발 기준으로 사용합니다. API·추론 필드는 공통 계약에서 관리합니다. 실제 구현 상태는 [현재 상태](current_status.md)를 따릅니다.

## 전체 처리 구조

```text
Streamlit → EC2 백엔드 → S3 원본 영상 저장
→ Runpod GPU Pod가 업로드 영상을 원본 시간순으로 처리
→ Pod worker: X3D-S 후보 구간 → 후보 장면의 YOLO11s 객체 정보
→ S3 분석 영상·대표 프레임·JSON 저장
→ EC2 백엔드에서 외부 VLM API 호출 → RAG 검색
→ DB 작업 상태·리포트 저장 → Streamlit 결과 표시
```

초기 구성에서는 SQS와 DLQ를 사용하지 않습니다. Runpod GPU Pod의 상시 worker가 heartbeat를 보내고 업로드 영상 작업을 DB lease로 가져가며, 처리 중 event를 BE에 부분 등록합니다. 작업·이벤트 상태는 DB에 영속 저장합니다.

## 초기 배포 단위

```text
EC2
├── Streamlit
├── FastAPI 백엔드
└── BE 작업 프로세스 (제출·회수·VLM/RAG 후속 처리)

Runpod GPU Pod
├── supervisor / health API
├── video decoder / chronological frame buffer
├── X3D-S·YOLO11s inference worker
└── S3 uploader / event client

AWS
├── S3
├── PostgreSQL 제안 (최종 배포 선택 미정)
└── CloudWatch
```

처음에는 Streamlit과 백엔드를 같은 EC2 인스턴스에서 실행합니다. Streamlit은 백엔드 API를 통해 업로드와 분석을 요청하며, GPU 추론은 상시 Runpod GPU Pod에서 실행합니다. Pod supervisor·재시작·영상 처리 pacing은 배포 전에 확정합니다.

## 모델·학습 기본 구조

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

위 트리는 모델·학습 기본 구조를 설명합니다. 현재 추가된 PRD와 역할·계약·기록 문서는 [문서 목록](README.md)을 참고하세요. 추천 코드와 세부 폴더는 아직 생성하지 않았습니다. 인계할 모델 코드·테스트·노트북은 검토 후 기존 책임에 맞게 연결합니다.

## 폴더 책임

| 위치 | 책임 |
| --- | --- |
| `src/accident_vision/` | 로컬과 Runpod worker가 함께 사용하는 객체 탐지, 충돌 의심 탐지, 영상 파이프라인 및 추론 계약 |
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
| `docs/` | `contracts/service_contract.md`, `roles/`, `requirements.md`, `PROGRESS.md` | 현재 PRD의 계약·역할·요구사항·실행 기록 |

대용량 가중치와 데이터 원본은 저장소에 직접 추가하지 않고 저장 위치를 문서화합니다. 학습 노트북과 Colab 전용 코드는 운영 추론 패키지에서 import하지 않습니다.

## 결정 후 생성할 폴더

| 폴더 | 생성 조건 |
| --- | --- |
| `apps/streamlit/` | 화면 담당과 API 계약 확정 |
| `services/backend/` | FastAPI와 DB 선택 확정 |
| `deploy/runpod/` | Runpod Pod template·container image·supervisor·가중치·worker 코드 인계 완료 |
| `deploy/ec2/` | EC2 인스턴스·프로세스 실행·접속 방식 확정 |
| `rag/` | 문서 출처·임베딩·저장소 확정 |

## 초기 구현 순서

1. 모델 가중치와 설정 인계 및 SHA256 확인
2. 코드·설정을 로컬에서 준비하고 승인한 GPU 환경에서 공통 추론 확인
3. 공통 계약 초안 검토·가상 응답으로 FE/BE 착수 (모델 연결과 병행 가능)
4. Runpod worker에서 같은 추론 코드 실행
5. S3 입력·결과 저장 연결
6. EC2 백엔드의 분석 제출·상태 조회 구현
7. Streamlit과 백엔드 연결
8. VLM 구조화 응답 구현
9. RAG 검색과 리포트 연결
10. CloudWatch 로그와 실패 상태 검증

첫 구현은 샘플 영상 업로드·분석 방식으로 검증합니다. 실시간 CCTV 스트림 입력은 별도 범위 결정 후 추가합니다.
