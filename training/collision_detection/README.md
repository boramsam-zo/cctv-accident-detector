# 충돌 의심 탐지 학습

X3D-S 및 기존 충돌 모델의 학습 노트북, 설정, 평가 자료를 이곳에 둡니다. 운영 추론 코드는 `src/accident_vision/`에 둡니다.

## 추천 파일

| 파일 | 내용 |
| --- | --- |
| `README.md` | 클립 라벨 기준, 데이터 분할, 모델 버전과 평가 결과 요약 |
| `configs/train_x3d_s.yaml` | 프레임 샘플링, 클립 길이, 학습 하이퍼파라미터 |
| `notebooks/train_x3d_s.ipynb` | X3D-S 학습 및 실험 기록 |
| `notebooks/evaluate_x3d_s.ipynb` | 충돌 의심 탐지 성능과 오탐·미탐 분석 |

기존 모델 자료를 인계받으면 모델별 차이를 README에 추가합니다. 학습 전용 의존성과 경로는 운영 추론 패키지에 넣지 않습니다.
