# Modal 추론 연결 계약 v1

백엔드의 별도 작업 프로세스가 `queued` 실행을 찾고, 배포된 `analyze_video_job` 함수를 `spawn()`으로 제출한다. `modal_call_id`를 `runs` 테이블에 저장한 뒤 `FunctionCall.from_id(call_id).get(timeout=0)`으로 완료를 확인한다. 영상 업로드·상태·근거·검토에 쓰는 공개 API는 v0.2 응답 모양을 유지한다.

Modal 입력은 `schema_version=modal-inference-v1`, `job_id`, `run_id`, `source_video_id`, `input_object={bucket,key,sha256}`, `output_prefix`, `attempt`, `analysis_profile`, `duration_seconds`다. 원본 영상은 `input_object.bucket`에서, 가중치는 Modal `cctv-s3` Secret의 `MODEL_WEIGHTS_S3_BUCKET`에서 읽는다. 각 가중치의 객체 키와 SHA256도 이 Secret에 둔다. Modal은 입력과 가중치의 SHA256을 확인하고 X3D-S 후보 시각 및 YOLO 객체 정보를 계산한다. 결과 clip, frame, event manifest, final manifest를 입력 영상 버킷의 `output_prefix` 아래에 영구 저장한다. 반환값에는 `run_id`, event manifest 경로·SHA256 목록, final manifest 경로·SHA256만 넣는다.

백엔드는 반환된 모든 경로가 해당 실행의 `output_prefix` 아래인지 확인하고, manifest와 근거 객체의 SHA256 및 영상 시각 범위를 검증한 뒤 DB에 등록한다. 후보가 있으면 Gemini 후처리로 이동한다. 후보가 없으면 VLM·RAG를 건너뛰고 `no_candidates`로 완료한다. GPU 호출이 실패하거나 결과 검증이 실패하면 실행은 `failed`가 된다. 사람 검토 API는 그대로 유지한다.

인계받은 오프라인 X3D-S·YOLO 코드는 `src/accident_vision`에 넣었다. 현재 구현은 **파일 전체를 오프라인으로 분석**하므로 Modal 입력의 `analysis_mode`는 `offline_video`다. 완료 전 후보 등록이나 원본 속도 1× 재생은 제공하지 않는다. 실제 GPU 및 S3 통합은 아직 검증되지 않았다.

현재 코드에는 이전 내부 worker API의 호환 경로가 남아 있으나 Modal 작업 경로에서는 사용하지 않는다. 현재 GPU 연결 계약은 이 문서의 함수 입력·S3 결과 회수 방식이다.
