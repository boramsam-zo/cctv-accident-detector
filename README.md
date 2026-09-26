# CCTV Accident Detector

영상에서 객체와 충돌 의심 구간을 분석하는 프로젝트입니다.

현재는 모델 자산과 공통 추론 패키지를 위한 초기 폴더 구조만 준비했습니다. 서비스 및 배포 폴더는 관련 결정 후 추가합니다. 구조와 구현 순서는 [프로젝트 폴더 구조](docs/PROJECT_FOLDER_STRUCTURE.md)를 참고하세요.

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
