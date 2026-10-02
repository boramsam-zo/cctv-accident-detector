"""Minimal numeric test UI for the real upload -> Modal -> Gemini path."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import streamlit as st

from apps.streamlit.backend_client import BackendClient, BackendError
from apps.streamlit.e2e_metrics import (
    candidate_clip_records,
    rag_input_records,
    summarize_result,
    vlm_failure_records,
    vlm_io_records,
)


TERMINAL_STATUSES = {"completed", "partial", "failed"}
DETECTION_READY_STATUS = "awaiting_vlm"
POLL_SECONDS = 3


def render_metrics(result: dict[str, Any], elapsed_seconds: float) -> None:
    values = summarize_result(result)
    first = st.columns(5)
    first[0].metric("경과 시간 (초)", f"{elapsed_seconds:.1f}")
    first[1].metric("상태 코드", values["status_code"])
    first[2].metric("처리 구간", values["predicted_windows"])
    first[3].metric("전체 구간", values["scheduled_windows"])
    first[4].metric("사고 후보", values["candidate_count"])

    second = st.columns(5)
    second[0].metric("최대 후보 점수", f"{values['max_candidate_score']:.4f}")
    second[1].metric("VLM 완료", values["vlm_completed_count"])
    second[2].metric("VLM 관찰", values["vlm_observation_count"])
    second[3].metric("RAG 입력", values["rag_input_count"])
    second[4].metric("오류", values["error_count"])

    scheduled = int(values["scheduled_windows"])
    processed = int(values["predicted_windows"])
    st.progress(min(processed / scheduled, 1.0) if scheduled else 0.0)
    st.caption(
        f"status={result.get('status', 'unknown')} · "
        f"미분류={values['unclassified_windows']} · 대기={values['pending_windows']} · "
        f"VLM 불확실성={values['vlm_uncertainty_count']}"
    )


def render_actual_vlm_status(result: dict[str, Any]) -> None:
    """실제 영상 후보에 대한 VLM 호출 결과를 연결 확인과 구분해 표시한다."""
    candidates = result.get("candidates") or []
    if result.get("status") == DETECTION_READY_STATUS:
        st.info("VLM 전송 대기 중: 아직 Gemini 요청을 보내지 않았습니다.")
        return
    if not candidates:
        if result.get("status") in TERMINAL_STATUSES:
            st.info("실제 VLM 요청 없음: 사고 후보가 생성되지 않았습니다.")
        return
    statuses = [(candidate.get("vlm") or {}).get("status", "pending") for candidate in candidates]
    completed = statuses.count("completed")
    failed = statuses.count("failed")
    if failed:
        st.error(f"실제 영상 VLM 응답 실패: {failed}/{len(candidates)}건")
    elif completed == len(candidates):
        models = sorted({
            (candidate.get("vlm") or {}).get("provider_model")
            for candidate in candidates
            if (candidate.get("vlm") or {}).get("provider_model")
        })
        st.success(f"실제 영상 VLM 응답 정상: {completed}/{len(candidates)}건 · {', '.join(models)}")
    else:
        st.info(f"실제 영상 VLM 처리 중: {completed}/{len(candidates)}건 완료")


def render_vlm_io(result: dict[str, Any]) -> None:
    records = vlm_io_records(result)
    if not records:
        st.info("표시할 VLM 입출력이 없습니다.")
        return
    st.subheader("VLM 입력·출력 확인")
    for index, record in enumerate(records, start=1):
        with st.expander(f"후보 {index} · {record['event_id']} · {record['status']}", expanded=index == 1):
            input_column, output_column = st.columns(2)
            with input_column:
                st.markdown("**Gemini 입력**")
                st.json(record["input"])
            with output_column:
                st.markdown("**Gemini 출력**")
                st.json(record["output"])


def render_rag_inputs(result: dict[str, Any]) -> None:
    """Show the exact event ID + VLM payload that will be sent to RAG."""
    records = rag_input_records(result)
    if not records:
        return

    st.subheader("RAG 전달 최종 JSON")
    available = [record for record in records if record["rag_input"]]
    if not available:
        st.info("VLM 분석이 완료되면 event_id와 VLM 결과를 합친 RAG 입력 JSON이 표시됩니다.")
        return

    st.caption("백엔드에 저장된 실제 rag_input 값입니다. 이 JSON이 다음 RAG 단계의 입력으로 사용됩니다.")
    for index, record in enumerate(available, start=1):
        with st.expander(
            f"후보 {index} · {record['event_id']}",
            expanded=index == 1,
        ):
            st.json(record["rag_input"], expanded=True)


def render_vlm_failures(client: BackendClient, result: dict[str, Any]) -> None:
    """Explain VLM failures and allow retrying Gemini without rerunning detection."""
    failures = vlm_failure_records(result)
    if not failures:
        return

    st.subheader("VLM 분석 실패")
    for failure in failures:
        st.error(
            f"{failure['event_id']} · {failure['reason_code']}\n\n"
            f"{failure['error_message']}"
        )
    st.caption("재시도하면 사고 탐지와 클립 추출은 유지하고 실패한 후보만 Gemini에 다시 전송합니다.")
    if st.button("VLM 분석 다시 시도", type="primary"):
        try:
            with st.spinner("실패한 VLM 분석을 다시 요청하는 중..."):
                client.start_vlm(
                    st.session_state.e2e_job_id,
                    f"e2e-vlm-retry-{uuid4().hex}",
                )
            st.session_state.e2e_finished_at = None
            st.rerun()
        except BackendError as exc:
            st.error(f"VLM 재시도 요청 실패: {exc}")


def _render_candidate_clips_legacy(client: BackendClient, result: dict[str, Any]) -> None:
    records = candidate_clip_records(result)
    if not records:
        return
    st.subheader("사고 후보 클립")
    for index, record in enumerate(records, start=1):
        title = f"후보 {index} · {record['event_id']}"
        with st.expander(title, expanded=index == 1):
            st.caption(
                f"후보 시각 {record['candidate_time_s']}초 · "
                f"클립 {record['clip_start_seconds']}~{record['clip_end_seconds']}초"
            )
            if not record["clip_asset_id"]:
                st.warning("이 후보에는 생성된 클립이 없습니다.")
                continue
            try:
                asset = client.asset_url(record["clip_asset_id"])
                st.video(asset["url"], format=asset.get("content_type", "video/mp4"))
                st.caption(f"asset_id: {record['clip_asset_id']}")
            except BackendError as exc:
                st.error(f"클립 URL 발급 실패: {exc}")


def render_candidate_clips(client: BackendClient, result: dict[str, Any]) -> None:
    """Show the untouched evidence clip beside the per-frame YOLO overlay."""
    records = candidate_clip_records(result)
    if not records:
        return
    st.subheader("사고 후보 클립")
    for index, record in enumerate(records, start=1):
        with st.expander(f"후보 {index} · {record['event_id']}", expanded=index == 1):
            st.caption(
                f"후보 시각 {record['candidate_time_s']}초 · "
                f"클립 {record['clip_start_seconds']}~{record['clip_end_seconds']}초"
            )
            columns = st.columns(2)
            assets = (
                (columns[0], "원본 클립", record.get("clip_asset_id")),
                (columns[1], "YOLO 객체 인식 클립", record.get("annotated_clip_asset_id")),
            )
            for column, label, asset_id in assets:
                with column:
                    st.markdown(f"**{label}**")
                    if not asset_id:
                        st.info("이 분석 결과에는 해당 클립이 없습니다.")
                        continue
                    try:
                        asset = client.asset_url(asset_id)
                        st.video(asset["url"], format=asset.get("content_type", "video/mp4"))
                        st.caption(f"asset_id: {asset_id}")
                    except BackendError as exc:
                        st.error(f"클립 URL 발급 실패: {exc}")


def load_profiles(client: BackendClient) -> list[dict]:
    return [profile for profile in client.analysis_profiles() if profile.get("enabled")]


def render_profile_registration(client: BackendClient) -> None:
    with st.expander("모델·가중치 프로필 등록"):
        st.caption("X3D와 객체 탐지 가중치를 S3에 업로드하고 선택 가능한 프로필로 저장합니다.")
        st.caption("현재 로더는 X3D-S 호환 state dict와 Ultralytics YOLO11 가중치를 지원합니다.")
        with st.form("profile-registration", clear_on_submit=True):
            display_name = st.text_input("프로필 이름", placeholder="예: X3D-S epoch 40 + YOLO11s custom")
            description = st.text_area("설명", height=80)
            left, right = st.columns(2)
            with left:
                accident_family = st.selectbox("사고 모델 계열", options=["X3D-S"])
                accident_weights = st.file_uploader(
                    "사고 모델 가중치 (.pt/.pth)", type=["pt", "pth"], key="profile-x3d")
            with right:
                object_family = st.selectbox("객체 모델 계열", options=["YOLO11"])
                object_weights = st.file_uploader(
                    "객체 모델 가중치 (.pt/.pth)", type=["pt", "pth"], key="profile-yolo")
            submitted = st.form_submit_button("S3 업로드 및 프로필 등록", type="primary")
        if submitted:
            if not display_name.strip() or accident_weights is None or object_weights is None:
                st.error("프로필 이름과 두 가중치 파일을 모두 입력해 주세요.")
                return
            try:
                with st.spinner("가중치 업로드 및 DB 등록 중..."):
                    profile = client.create_analysis_profile(
                        display_name=display_name.strip(), description=description.strip(),
                        accident_family=accident_family.strip(), object_family=object_family.strip(),
                        accident_name=accident_weights.name, accident_data=accident_weights.getvalue(),
                        object_name=object_weights.name, object_data=object_weights.getvalue(),
                    )
                st.session_state.e2e_profile_created = profile["analysis_profile_id"]
                st.rerun()
            except BackendError as exc:
                st.error(f"프로필 등록 실패: {exc}")


def start_analysis(client: BackendClient, uploaded_file: Any, profile_id: str,
                   vlm_model: str, vlm_prompt: str, vlm_prompt_mode: str) -> None:
    request_id = uuid4().hex
    video = client.upload_video(
        uploaded_file.name,
        uploaded_file.getvalue(),
        camera_id="e2e-test",
        key=f"e2e-upload-{request_id}",
    )
    job = client.create_job(
        video["source_video_id"],
        profile_id,
        f"e2e-job-{request_id}",
        vlm_model=vlm_model,
        vlm_prompt=vlm_prompt,
        vlm_prompt_mode=vlm_prompt_mode,
        defer_vlm=True,
    )
    st.session_state.e2e_job_id = job["job_id"]
    st.session_state.e2e_started_at = time.monotonic()
    st.session_state.e2e_finished_at = None
    st.session_state.e2e_result = None


def elapsed_seconds() -> float:
    end = st.session_state.e2e_finished_at
    if end is None:
        end = time.monotonic()
    return max(0.0, end - st.session_state.e2e_started_at)


def freeze_elapsed_time(status: str, finished_at: float | None, now: float) -> float | None:
    """Keep the first time at which the current analysis phase finished."""
    if finished_at is not None:
        return finished_at
    if status in TERMINAL_STATUSES | {DETECTION_READY_STATUS}:
        return now
    return None


@st.fragment(run_every=POLL_SECONDS)
def poll_job(client: BackendClient) -> None:
    try:
        result = client.get_job(st.session_state.e2e_job_id)
    except BackendError as exc:
        st.error(str(exc))
        return
    st.session_state.e2e_result = result
    st.session_state.e2e_finished_at = freeze_elapsed_time(
        result.get("status", "unknown"),
        st.session_state.e2e_finished_at,
        time.monotonic(),
    )
    render_metrics(result, elapsed_seconds())
    render_actual_vlm_status(result)
    if result.get("status") in TERMINAL_STATUSES | {DETECTION_READY_STATUS}:
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="CCTV E2E 수치 테스트", layout="wide")
    st.title("영상 분석 E2E 수치 테스트")
    st.caption("영상 업로드 → S3 → Modal 추론 → Gemini VLM 결과를 실제 백엔드 함수로 확인합니다.")

    client = BackendClient.from_env()
    if client is None:
        st.error("BACKEND_API_URL과 APP_API_KEY를 설정해 주세요.")
        st.stop()

    for key, default in {
        "e2e_job_id": None,
        "e2e_started_at": None,
        "e2e_finished_at": None,
        "e2e_result": None,
        "e2e_vlm_check": None,
        "e2e_profile_created": None,
        "e2e_prompt_preset": None,
        "e2e_loaded_prompt_preset": None,
        "e2e_vlm_prompt": "",
    }.items():
        st.session_state.setdefault(key, default)

    try:
        health = client.health()
        profiles = load_profiles(client)
        vlm_options = client.vlm_options()
    except BackendError as exc:
        st.error(f"백엔드 연결 실패: {exc}")
        st.stop()

    st.caption(f"백엔드 상태: {health.get('status', 'unknown')} · 사용 가능 프로필: {len(profiles)}")
    if st.session_state.e2e_profile_created:
        st.success(f"프로필 등록 완료: {st.session_state.e2e_profile_created}")
        st.session_state.e2e_profile_created = None
    render_profile_registration(client)
    if not profiles:
        st.error("선택할 수 있는 분석 프로필이 없습니다.")
        st.stop()
    if not vlm_options.get("models"):
        st.error("선택할 수 있는 Gemini 모델이 없습니다.")
        st.stop()

    profile_by_id = {profile["analysis_profile_id"]: profile for profile in profiles}
    selected_profile = st.selectbox(
        "모델/가중치 프로필",
        options=list(profile_by_id),
        format_func=lambda profile_id: (
            f"{profile_by_id[profile_id].get('display_name', profile_id)} ({profile_id})"
        ),
        disabled=bool(st.session_state.e2e_job_id and not st.session_state.e2e_finished_at),
    )
    profile_models = profile_by_id[selected_profile].get("models") or {}
    if profile_models:
        accident = profile_models.get("accident") or {}
        objects = profile_models.get("objects") or {}
        st.caption(
            f"사고 모델: {accident.get('family', '-')} / "
            f"{(accident.get('weights') or {}).get('sha256', '-')[:12]} · "
            f"객체 모델: {objects.get('family', '-')} / "
            f"{(objects.get('weights') or {}).get('sha256', '-')[:12]}"
        )
    selected_model = st.selectbox(
        "Gemini VLM 모델",
        options=vlm_options["models"],
        index=(vlm_options["models"].index(vlm_options["default_model"])
               if vlm_options.get("default_model") in vlm_options["models"] else 0),
        disabled=bool(st.session_state.e2e_job_id and not st.session_state.e2e_finished_at),
    )
    if st.button("선택 모델 연결 확인", disabled=bool(
            st.session_state.e2e_job_id and not st.session_state.e2e_finished_at)):
        try:
            with st.spinner("Gemini에 최소 요청을 보내는 중..."):
                st.session_state.e2e_vlm_check = client.check_vlm(selected_model)
        except BackendError as exc:
            st.session_state.e2e_vlm_check = {
                "available": False, "model": selected_model, "error_code": exc.code or type(exc).__name__
            }
    check = st.session_state.e2e_vlm_check
    if check and check.get("model") == selected_model:
        if check.get("available"):
            st.success(
                f"현재 사용 가능 · 응답 {check.get('latency_ms', 0)}ms · "
                f"{check.get('response_preview', '')}"
            )
        else:
            st.error(f"현재 응답 실패 · {check.get('error_code', 'unknown_error')}")
    prompt_mode = st.selectbox(
        "프롬프트 적용 방식",
        options=vlm_options.get("prompt_modes", ["prepend"]),
        index=(vlm_options.get("prompt_modes", ["prepend"]).index(
            vlm_options.get("default_prompt_mode", "prepend"))
            if vlm_options.get("default_prompt_mode", "prepend")
            in vlm_options.get("prompt_modes", ["prepend"]) else 0),
        format_func=lambda mode: "기본 규칙 앞에 추가" if mode == "prepend" else "전체 지시 교체",
        disabled=bool(st.session_state.e2e_job_id and not st.session_state.e2e_finished_at),
    )
    prompt_presets = vlm_options.get("prompt_presets") or [{
        "id": "version1",
        "name": "version1 · 기존 장면 분석",
        "prompt": vlm_options.get("prompt_default", ""),
    }]
    preset_by_id = {preset["id"]: preset for preset in prompt_presets}
    default_preset = vlm_options.get("default_prompt_preset", "version1")
    if st.session_state.e2e_prompt_preset not in preset_by_id:
        st.session_state.e2e_prompt_preset = (
            default_preset if default_preset in preset_by_id else next(iter(preset_by_id))
        )
    selected_prompt_preset = st.selectbox(
        "프롬프트 초안",
        options=list(preset_by_id),
        format_func=lambda preset_id: preset_by_id[preset_id]["name"],
        key="e2e_prompt_preset",
        disabled=bool(st.session_state.e2e_job_id and not st.session_state.e2e_finished_at),
    )
    if st.session_state.e2e_loaded_prompt_preset != selected_prompt_preset:
        st.session_state.e2e_vlm_prompt = preset_by_id[selected_prompt_preset]["prompt"]
        st.session_state.e2e_loaded_prompt_preset = selected_prompt_preset
    vlm_prompt = st.text_area(
        "VLM 프롬프트",
        key="e2e_vlm_prompt",
        height=360,
        max_chars=12000,
        help="초안을 불러온 뒤 자유롭게 수정할 수 있습니다. 전체 교체를 선택해도 JSON 응답 스키마는 계속 적용됩니다.",
        disabled=bool(st.session_state.e2e_job_id and not st.session_state.e2e_finished_at),
    )
    uploaded_file = st.file_uploader("MP4 영상", type=["mp4"])

    if st.button("분석 시작", type="primary", disabled=uploaded_file is None):
        try:
            with st.spinner("영상 업로드와 작업 등록 중..."):
                start_analysis(
                    client, uploaded_file, selected_profile, selected_model,
                    vlm_prompt, prompt_mode,
                )
            st.rerun()
        except BackendError as exc:
            st.error(f"작업 생성 실패: {exc}")

    if st.session_state.e2e_job_id:
        st.code(st.session_state.e2e_job_id, language=None)
        if st.session_state.e2e_finished_at and st.session_state.e2e_result:
            selected = (st.session_state.e2e_result.get("execution_config") or {}).get("vlm") or {}
            st.caption(
                f"실행 Gemini 모델: {selected.get('model', '-')} · "
                f"프롬프트 방식: {selected.get('prompt_mode', 'prepend')} · "
                f"입력 길이: {len(selected.get('prompt', ''))}자"
            )
            render_metrics(st.session_state.e2e_result, elapsed_seconds())
            render_actual_vlm_status(st.session_state.e2e_result)
            render_candidate_clips(client, st.session_state.e2e_result)
            if st.session_state.e2e_result.get("status") == DETECTION_READY_STATUS:
                st.info("사고 후보 추출이 끝났습니다. 확인 후 아래 버튼으로 VLM 분석을 시작하세요.")
                if st.button("후보 클립을 VLM에 전송", type="primary"):
                    try:
                        with st.spinner("VLM 분석 요청 중..."):
                            client.start_vlm(
                                st.session_state.e2e_job_id,
                                f"e2e-vlm-{uuid4().hex}",
                            )
                        st.session_state.e2e_finished_at = None
                        st.rerun()
                    except BackendError as exc:
                        st.error(f"VLM 요청 실패: {exc}")
            render_vlm_failures(client, st.session_state.e2e_result)
            render_vlm_io(st.session_state.e2e_result)
            render_rag_inputs(st.session_state.e2e_result)
            from apps.streamlit.app import render_report, render_retrieval

            for candidate in st.session_state.e2e_result.get("candidates", []):
                if candidate.get("report"):
                    st.subheader(f"최종 리포트 · {candidate['event_id']}")
                    render_report(candidate)
                    render_retrieval(candidate)
        else:
            poll_job(client)


if __name__ == "__main__":
    main()
