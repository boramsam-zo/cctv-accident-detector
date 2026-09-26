# 공통 영상 추론 패키지

로컬 실행과 Modal GPU 작업에서 같은 코드를 import하는 운영 추론 패키지입니다.

## 추천 파일

| 파일 | 내용 |
| --- | --- |
| `schemas.py` | 영상 분석 요청, 탐지 결과, 사고 의심 이벤트의 공통 데이터 계약 |
| `detection/loader.py`, `predict.py` | YOLO11s 가중치 로드와 객체 탐지 |
| `detection/preprocessing.py`, `visualize.py` | 입력 프레임 전처리와 탐지 결과 시각화 |
| `collision/loader.py`, `predict.py` | X3D-S 가중치 로드와 충돌 의심 확률 추론 |
| `collision/preprocessing.py`, `postprocessing.py` | 클립 전처리와 점수 후처리 |
| `pipeline/analyze_video.py` | 영상 입력부터 두 모델 추론과 결과 생성까지 연결 |
| `pipeline/event_grouping.py`, `result_builder.py` | 연속 의심 구간 묶음과 결과 JSON 생성 |
| `io/video_file.py`, `s3_video.py` | 로컬 영상과 S3 영상 입력 처리 |

모델 코드와 추론 계약이 정해질 때 해당 파일을 추가합니다. 학습 노트북과 Colab 전용 코드는 이 패키지에서 import하지 않습니다.
