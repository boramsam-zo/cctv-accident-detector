# 객체 탐지 학습

YOLO11s 학습 노트북, 설정, 평가 자료를 이곳에 둡니다. 운영 추론 코드는 `src/accident_vision/`에 둡니다.

## 추천 파일

| 파일 | 내용 |
| --- | --- |
| `README.md` | 데이터 출처, 학습 재현 절차, 모델 버전과 평가 결과 요약 |
| `configs/train.yaml` | YOLO11s 학습 하이퍼파라미터와 데이터셋 설정 참조 |
| `notebooks/train_yolo11s.ipynb` | 실험 또는 학습 과정을 기록한 노트북 |
| `notebooks/evaluate_yolo11s.ipynb` | 검증·테스트 성능과 오류 사례 분석 |

데이터 원본과 학습 결과물은 저장 위치를 문서화하고, 대용량 파일을 저장소에 직접 추가하지 않습니다. 노트북의 Colab 경로는 운영 코드에서 사용하지 않습니다.
