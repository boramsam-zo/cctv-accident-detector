# Modal GPU 추론

`app.py`는 영상 버킷의 원본 MP4와 별도 가중치 버킷의 X3D-S·YOLO11s 가중치를 읽습니다. 후보 clip, 대표 frame, event/final manifest는 **영상 버킷**의 할당된 `output_prefix`에 저장합니다. 백엔드는 Modal `call_id`를 DB에 보관하고 별도 worker에서 결과를 회수합니다. 원본/근거 파일과 최종 상태는 Modal 결과 핸들이 만료되어도 S3와 PostgreSQL에 남습니다.

## 준비

1. 저장소 루트에서 `uv sync --locked --group dev`를 실행합니다.
2. Modal CLI/SDK는 `uv pip install --python .venv/bin/python -r deploy/modal/requirements.txt`로 설치합니다. 현재 네트워크 제한 때문에 Modal 의존성은 `uv.lock`에 아직 반영되지 않았습니다. 패키지 설치 시 인터넷 연결이 필요합니다.
3. `uv run --no-sync modal token new`로 개발 계정을 인증하고 `uv run --no-sync modal environment create dev`로 별도 환경을 만듭니다.
4. 가중치 전용 S3 버킷에 X3D-S epoch 7 및 YOLO11s 가중치를 올립니다. 영상 업로드와 추론 결과는 백엔드의 `S3_BUCKET`에 지정한 영상 버킷을 사용합니다. 인계 파일은 `.local/deployment_handoff/models/`에 있으며 Git에 넣지 않습니다.
5. Modal `dev` 환경에 `cctv-s3` Secret을 만듭니다. `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `MODEL_WEIGHTS_S3_BUCKET`, `X3D_WEIGHTS_S3_KEY`, `YOLO_WEIGHTS_S3_KEY`, `X3D_WEIGHTS_SHA256`, `YOLO_WEIGHTS_SHA256`을 포함해야 합니다. 해시는 실제 업로드한 파일과 일치해야 합니다. IAM 권한은 영상 버킷의 원본 읽기·결과 prefix 쓰기와 가중치 버킷의 모델 읽기에 필요한 범위로 제한합니다. 자격 증명은 코드나 PR에 넣지 않습니다.

예를 들어 영상 버킷이 `cctv-video-dev-bucket`이고 가중치 버킷이 `cctv-model-weights-bucket`이라면 로컬 백엔드 `.env`에는 `S3_BUCKET=cctv-video-dev-bucket`을 설정합니다. 아래 해시는 로컬 `.local/deployment_handoff/models/x3d_s.pt`, `yolo11s.pt` 기준입니다. 이 파일들을 각각 표시된 S3 키에 올렸을 때 Modal Secret에 다음 값을 설정합니다. 객체 키에는 `s3://`나 버킷 이름을 포함하지 않습니다.

```text
MODEL_WEIGHTS_S3_BUCKET=cctv-model-weights-bucket
YOLO_WEIGHTS_S3_KEY=models/yolo11s/best.pt
X3D_WEIGHTS_S3_KEY=models/x3d_s/best.pt
YOLO_WEIGHTS_SHA256=51b8873f49d6ddf8611de6e3bd2bc88fca00d6d5de62638791d01b25fd9a2dcf
X3D_WEIGHTS_SHA256=ca2db4a25c9cd2d859a7143932d911a3351beacc5193de3ada16f3115bea09bf
```

## 배포와 백엔드 실행

호스트에 Modal CLI가 설치돼 있다면 저장소 루트에서 실행합니다.

```bash
uv run --no-sync modal deploy --env dev deploy/modal/app.py
uv run --no-sync alembic upgrade head
uv run --no-sync python -m services.backend.run_worker
```

호스트에 Modal CLI가 없고 [개발용 Compose](../compose/README.md)를 사용 중이라면 앱 이미지에 CLI와 `app.py`가 포함돼 있습니다. `cctv-s3` Secret을 Modal `dev` 환경에 먼저 만든 뒤 저장소 루트에서 다음을 실행합니다. GPU 함수만 Modal에 배포하며, PostgreSQL/FastAPI/Streamlit은 Compose에 남습니다.

```bash
docker compose --env-file .env -f deploy/compose/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose/compose.yaml run --rm --no-deps worker modal deploy --env dev deploy/modal/app.py
```

백엔드/worker에는 `MODAL_ENVIRONMENT=dev`, `MODAL_APP_NAME=cctv-accident-inference`, `MODAL_FUNCTION_NAME=analyze_video_job`와 Modal 토큰을 설정합니다. 범용 버킷에서 개발 데이터를 분리하려면 `S3_KEY_PREFIX=dev/<개발자명>`을 지정합니다. 백엔드가 실제 S3를 사용할 때는 `S3_ENDPOINT_URL`을 비웁니다. Streamlit과 FastAPI의 공개 API 계약은 유지합니다.

현재 인계 추론 코드는 MP4를 메모리에 읽으며 120초를 넘는 영상은 거절합니다. 첫 GPU 추론, CUDA·PyTorchVideo 호환성, 실제 S3 권한은 Modal 계정에서 별도로 스모크 테스트해야 합니다. `dev`와 운영 환경의 Modal 앱·Secret은 분리합니다.
