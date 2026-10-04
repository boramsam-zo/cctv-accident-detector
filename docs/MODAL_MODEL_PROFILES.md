# Modal 모델·가중치 선택 구조

## 권장 구조

브라우저나 작업 요청에서 로컬 파일 경로, S3 버킷, 객체 키를 직접 받지 않는다. 로컬에서 가중치를 등록한 뒤 백엔드가 허용한 `analysis_profile_id`만 선택하게 한다.

1. 로컬 등록 명령이 가중치의 SHA-256을 계산하고 전용 S3 경로에 업로드한다.
2. 백엔드 모델 프로필 레지스트리에 모델명, 가중치 S3 URI, SHA-256, 전처리 버전, 임계값, 클래스 맵을 저장한다.
3. `GET /api/v1/analysis-profiles`는 활성 프로필만 화면에 제공한다.
4. 작업 생성 시 `analysis_profile_id`를 저장하고 Modal 요청에는 해당 프로필의 고정된 버전과 가중치 해시를 전달한다.
5. Modal은 허용된 프로필인지 확인하고 가중치를 내려받아 SHA-256을 검증한 뒤 추론한다.

예시 프로필은 다음과 같다.

```json
{
  "analysis_profile_id": "x3d-s-yolo11s-2026-09-30",
  "display_name": "X3D-S + YOLO11s v1",
  "enabled": true,
  "accident_model": {
    "family": "X3D-S",
    "weights_s3_uri": "s3://model-bucket/x3d/2026-09-30/model.pt",
    "weights_sha256": "...",
    "preprocessing_version": "x3d-v1"
  },
  "object_model": {
    "family": "YOLO11s",
    "weights_s3_uri": "s3://model-bucket/yolo/2026-09-30/model.pt",
    "weights_sha256": "..."
  },
  "candidate_threshold": 0.75
}
```

이 구조는 한 작업이 어떤 가중치로 실행됐는지 재현할 수 있고, 사용자가 임의의 S3 객체를 Modal에서 실행하는 문제를 막는다. Modal Volume은 이후 가중치 다운로드 시간을 줄이는 캐시로 추가할 수 있지만 프로필과 해시가 기준 정보여야 한다.

## 현재 구현 상태

테스트 페이지에서 X3D와 YOLO 가중치를 등록할 수 있다. 백엔드는 파일을 현재 영상 S3 버킷의 개발 prefix 아래에 업로드하고 `analysis_profiles` 테이블에 모델 계열, 객체 키, SHA-256, 크기와 원본 파일명을 저장한다. 작업 생성 시 선택한 프로필 전체를 실행 설정에 복사하고 Modal assignment에는 검증된 가중치 참조만 전달한다. Modal은 파일을 내려받은 뒤 SHA-256이 일치해야 모델을 로드한다.

기존 `ANALYSIS_PROFILE_ID` 프로필은 호환성을 위해 계속 표시되며 이 프로필만 Modal `cctv-s3` Secret의 기존 가중치 설정을 사용한다.
