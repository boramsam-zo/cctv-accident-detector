from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
DEMO_CASES_PATH = PROJECT_ROOT / "docs" / "contracts" / "demo-analysis-cases-v0.2.json"
HOVER_PREVIEW_MAX_BYTES = 8 * 1024 * 1024

VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}

STATUS_LABELS = {
    "queued": "분석 대기",
    "dispatching": "GPU 연결 중",
    "running": "영상 분석 중",
    "enriching": "후보 설명 생성 중",
    "completed": "분석 완료",
    "partial": "일부 분석 완료",
    "failed": "분석 실패",
}

STAGE_LABELS = {
    "accident": "사고 후보 탐지",
    "objects": "객체 분석",
    "evidence": "근거 생성",
    "vlm": "장면 설명",
    "rag": "문서 근거 검색",
    "report": "보고서 생성",
}

STAGE_ICONS = {
    "pending": "○",
    "running": "◉",
    "completed": "●",
    "skipped": "―",
    "failed": "!",
    "insufficient_evidence": "△",
}


@st.cache_data
def load_demo_cases() -> list[dict[str, Any]]:
    with DEMO_CASES_PATH.open(encoding="utf-8") as file:
        return json.load(file)["cases"]


def initialize_state(cases: list[dict[str, Any]]) -> None:
    defaults = {
        "uploaded_videos": [],
        "selected_upload_index": 0,
        "current_page": "intake",
        "analysis_requested": False,
        "selected_job_id": "demo-job-no-docs",
        "review_by_event": {},
        "request_key": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    available_ids = {case["job_id"] for case in cases}
    if st.session_state.selected_job_id not in available_ids:
        st.session_state.selected_job_id = cases[0]["job_id"]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600;700&family=Noto+Sans+KR:wght@400;500;600;700&display=swap');
        :root { --navy:#0f172a; --blue:#1d4ed8; --teal:#0f766e; --red:#dc2626; --line:#dbe3ef; }
        .stApp { background:radial-gradient(circle at 72% -10%,#eaf1ff 0,transparent 34%),#f6f8fc; color:#0f172a; font-family:'Noto Sans KR',sans-serif; }
        [data-testid="stHeader"] { display:none; }
        [data-testid="stSidebar"] { background: #0f1f36; border-right: 1px solid #203653; }
        [data-testid="stSidebar"] * { color: #e8eef8; }
        [data-testid="stSidebar"] .stButton button { background:#172b47; border-color:#36506f; color:#e8eef8; }
        [data-testid="stSidebar"] .stButton button:hover { background:#203957; border-color:#557394; color:#fff; }
        [data-testid="stSidebar"] .stButton button[kind="primary"] { background:#1d4ed8; border-color:#2563eb; color:#fff; }
        [data-testid="stSidebar"] [data-baseweb="select"] > div { background:#172b47 !important; border-color:#36506f !important; color:#e8eef8 !important; }
        [data-testid="stSidebar"] [data-baseweb="select"] span { color:#e8eef8 !important; }
        .block-container { max-width:1560px; padding-top:.8rem; padding-bottom:2rem; }
        h1, h2, h3, h4 { letter-spacing: -.025em; }
        .topbar {
            display:flex; align-items:center; justify-content:space-between; gap:1rem;
            background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:.66rem .9rem; margin-bottom:.8rem; box-shadow:0 8px 24px rgba(30,64,175,.06);
        }
        .brand { display:flex; align-items:center; gap:.7rem; }
        .brand-mark { width:34px; height:34px; display:grid; place-items:center; border-radius:7px; background:var(--blue); color:#fff; font-weight:800; }
        .brand-title { font-size:1rem; font-weight:800; line-height:1.15; }
        .brand-sub { color:#64748b; font-size:.69rem; }
        .system-state { font:600 .72rem 'JetBrains Mono'; color:#075f59; background:#e9f8f5; border-radius:999px; padding:.42rem .75rem; }
        .demo-state { font:700 .7rem 'JetBrains Mono'; color:#9a3412; background:#fff0e7; border-radius:5px; padding:.38rem .65rem; }
        .workspace-title { margin:.15rem 0 .7rem; }
        .workspace-title h1 { font-size:1.45rem; margin:0; }
        .workspace-title p { color:#64748b; margin:.25rem 0 0; font-size:.85rem; }
        .panel {
            background: white; border: 1px solid var(--line); border-radius: 10px;
            padding: 1rem 1.1rem; margin-bottom: .8rem; box-shadow:0 1px 3px rgba(15,23,42,.04);
        }
        .job-compact { display:flex; align-items:center; justify-content:space-between; gap:.6rem; background:#fff; border:1px solid var(--line); border-radius:10px 10px 0 0; padding:.6rem .8rem; }
        .job-facts { background:#f8fafc; border:1px solid var(--line); border-top:0; border-radius:0 0 10px 10px; padding:.45rem .8rem; margin-bottom:.6rem; font-size:.78rem; color:#334155; }
        .job-meta { color:#64748b; font:500 .67rem 'JetBrains Mono'; margin-top:.15rem; }
        .metrics-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin-bottom:.65rem; }
        .metric-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:.65rem .8rem; position:relative; overflow:hidden; }
        .metric-card:before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background:#2563eb; }
        .metric-label { color:#64748b; font-size:.7rem; font-weight:700; }
        .metric-value { color:#0f172a; font:700 1.35rem 'JetBrains Mono'; margin-top:.22rem; }
        .status-chip {
            display:inline-block; border-radius:999px; padding:.28rem .68rem;
            background:#dbeafe; color:#1e40af; font:700 .72rem 'JetBrains Mono';
        }
        .demo-chip {
            display:inline-block; border-radius:4px; padding:.28rem .6rem;
            background:#fff0e7; color:#a64722; font:700 .68rem 'JetBrains Mono'; margin-left:.3rem;
        }
        .section-kicker { color:#1d4ed8; font:700 .7rem 'JetBrains Mono'; letter-spacing:.05em; margin-bottom:.28rem; }
        .video-shell { background:#17243a; border-radius:10px; overflow:hidden; border:1px solid #253a55; box-shadow:0 6px 18px rgba(15,23,42,.16); }
        .video-header { background:#17243a; border-radius:10px 10px 0 0; display:flex; justify-content:space-between; align-items:center; padding:.62rem .85rem; color:#e8eef8; font:600 .7rem 'JetBrains Mono'; border-bottom:1px solid #31445f; }
        .video-live { color:#fff; background:#b91c1c; padding:.18rem .45rem; border-radius:3px; margin-right:.45rem; }
        .video-empty { min-height:250px; display:grid; place-items:center; color:#94a3b8; text-align:center; background:linear-gradient(145deg,#142238,#22344e); position:relative; overflow:hidden; }
        .video-empty > div { position:relative; z-index:1; }
        .video-empty:before { content:''; position:absolute; width:240px; height:240px; border:1px solid rgba(148,163,184,.08); border-radius:50%; box-shadow:0 0 0 55px rgba(148,163,184,.025),0 0 0 110px rgba(148,163,184,.018); }
        .video-footer { background:#17243a; border-radius:0 0 10px 10px; margin-top:-1rem; padding:.65rem .85rem; color:#cbd5e1; font:500 .68rem 'JetBrains Mono'; border-top:1px solid #31445f; }
        .timeline { height:7px; border-radius:9px; background:#3b4c64; position:relative; overflow:hidden; margin:.45rem 0; }
        .timeline-fill { height:100%; background:#2563eb; }
        .candidate-marker { position:absolute; top:0; bottom:0; width:12px; background:#dc2626; box-shadow:0 0 8px #ef4444; }
        .evidence-card { border-left:3px solid #dc2626; background:#fff7f6; border-radius:3px 8px 8px 3px; padding:.8rem .9rem; margin:.6rem 0; }
        .score { color:#b91c1c; font:700 .74rem 'JetBrains Mono'; }
        .analysis-box { background:#f1f5fb; border-radius:7px; padding:.85rem; margin:.5rem 0; }
        .analysis-box p { margin:.2rem 0; }
        .analysis-label { color:#1d4ed8; font:700 .68rem 'JetBrains Mono'; }
        .rag-item { background:#eef4ff; border-radius:6px; padding:.75rem; margin:.45rem 0; }
        .upload-row { display:flex; justify-content:space-between; align-items:center; gap:1rem; background:#fff; border:1px solid var(--line); border-radius:7px; padding:.62rem .75rem; margin:.4rem 0; }
        .upload-name { font-size:.8rem; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .upload-meta { color:#64748b; font:500 .65rem 'JetBrains Mono'; }
        .upload-ready { color:#047857; background:#ecfdf5; padding:.22rem .48rem; border-radius:999px; font:700 .64rem 'JetBrains Mono'; white-space:nowrap; }
        .channel-head { display:flex; justify-content:space-between; align-items:center; margin:.9rem 0 .55rem; }
        .channel-count { color:#1e40af; background:#dbeafe; border-radius:999px; padding:.25rem .55rem; font:700 .65rem 'JetBrains Mono'; }
        .channel-meta { display:flex; justify-content:space-between; gap:.5rem; color:#64748b; font:500 .65rem 'JetBrains Mono'; margin:-.15rem 0 .55rem; }
        .channel-title { height:2.5rem; display:flex; align-items:center; font-size:.8rem; font-weight:750; line-height:1.25; overflow:hidden; word-break:break-all; }
        [class*="st-key-open-card-"] { display:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"] { border-color:#dbe3ef; border-radius:9px; box-shadow:0 2px 8px rgba(15,23,42,.04); background:#fff; }
        [data-testid="stVideo"] { aspect-ratio:16 / 9; background:#0f172a; border-radius:7px; overflow:hidden; }
        [data-testid="stVideo"] video { width:100% !important; height:100% !important; object-fit:cover !important; }
        .mono { font-family:'JetBrains Mono'; }
        .stage {
            display:flex; justify-content:space-between; align-items:center;
            padding:.58rem .1rem; border-bottom:1px solid #edf1f6; font-size:.8rem;
        }
        .stage:last-child { border:0; }
        .stage-state { color:#0f766e; font:700 .68rem 'JetBrains Mono'; }
        div[data-testid="stForm"] { background:#fff; border-radius:10px; border-color:var(--line); }
        div[data-testid="stFileUploader"] section { background:#f8fafc; border-color:#b8c7dd; }
        div[data-testid="stTabs"] button { font-weight:700; }
        button[data-baseweb="tab"][aria-selected="true"] { color:#1d4ed8 !important; }
        div[data-baseweb="tab-highlight"] { background-color:#1d4ed8 !important; }
        div[data-testid="stNotification"] { border-radius:8px; }
        [data-testid="stProgressBar"] > div > div { background:linear-gradient(90deg,#2563eb,#06b6d4); }
        .stButton button, .stFormSubmitButton button { border-radius:5px; }
        .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] { background:#1d4ed8; border-color:#1d4ed8; }
        @media (max-width: 900px) { .metrics-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        @media (max-width: 760px) { .system-state { display:none; } .block-container { padding:.7rem; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_message(result: dict[str, Any]) -> tuple[str, str]:
    status = result["status"]
    outcome = result["detection_outcome"]
    if status == "completed" and outcome == "no_candidates":
        return "success", "분석된 범위에서 사고 의심 후보가 없습니다."
    if status == "partial":
        return "warning", "일부 구간을 분류하지 못했습니다. 미확인 범위를 확인해 주세요."
    if status == "failed":
        return "error", "분석을 완료하지 못했습니다. 실패 단계와 재시도 가능 여부를 확인해 주세요."
    if status == "enriching":
        return "info", "사고 의심 후보를 찾았습니다. 장면 설명과 보고서를 생성하고 있습니다."
    if status in {"queued", "dispatching", "running"}:
        return "info", "분석 중입니다. 처리된 범위는 아래에서 확인할 수 있습니다."
    return "success", "분석이 완료되었습니다. 사고 의심 후보를 검토해 주세요."


def navigate_to(page: str) -> None:
    st.session_state.current_page = page


def render_sidebar(cases: list[dict[str, Any]]) -> dict[str, Any]:
    with st.sidebar:
        st.markdown("## ◉ AegisTraffic AI")
        st.caption("업로드 영상 사고 분석 플랫폼")
        st.divider()
        st.markdown("##### 메뉴")
        intake_active = st.session_state.current_page == "intake"
        analysis_active = st.session_state.current_page == "analysis"
        st.button(
            "＋ 영상 접수",
            key="nav-intake",
            type="primary" if intake_active else "secondary",
            use_container_width=True,
            on_click=navigate_to,
            args=("intake",),
        )
        st.button(
            "▣ 분석 워크스페이스",
            key="nav-analysis",
            type="primary" if analysis_active else "secondary",
            use_container_width=True,
            on_click=navigate_to,
            args=("analysis",),
        )
        st.divider()
        if st.session_state.uploaded_videos:
            st.markdown("##### 접수 영상")
            for index, video in enumerate(st.session_state.uploaded_videos):
                is_active = analysis_active and index == st.session_state.selected_upload_index
                display_name = video["name"] if len(video["name"]) <= 22 else f"{video['name'][:19]}..."
                st.button(
                    f"CAM_{index + 1:02d} · {display_name}",
                    key=f"sidebar-video-{index}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                    on_click=open_analysis,
                    args=(index,),
                )
            st.divider()
        st.markdown("##### 연결 상태")
        st.markdown("🟢 Streamlit UI 정상")
        st.markdown("🟡 FastAPI 데모 데이터")
        st.markdown("⚪ Runpod GPU 미연결")
        st.markdown("⚪ S3 미연결")
        st.divider()
        st.caption("AI는 사고 의심 후보와 근거를 제시합니다. 최종 판단은 검토자가 수행합니다.")
    return next(case for case in cases if case["job_id"] == st.session_state.selected_job_id)


def open_analysis(index: int) -> None:
    st.session_state.selected_upload_index = index
    st.session_state.current_page = "analysis"
    videos = st.session_state.uploaded_videos
    st.session_state.uploaded_videos = [
        {**video, "status": "queued" if video_index == index else video["status"]}
        for video_index, video in enumerate(videos)
    ]
    st.session_state.analysis_requested = True


def render_html_frame(html: str, fallback_height: int) -> None:
    # st.iframe은 최신 Streamlit에만 있으므로 구버전에서는 고정 높이의 components.html로 대체한다.
    if hasattr(st, "iframe"):
        st.iframe(html, height="content")
    else:
        import streamlit.components.v1 as components

        components.html(html, height=fallback_height)


def render_video_card(video: dict[str, Any], index: int) -> None:
    safe_name = escape(video["name"])
    size_mb = video["size_bytes"] / (1024 * 1024)
    status = "분석 대기" if video["status"] == "queued" else "접수 완료"
    suffix = Path(video["name"]).suffix.lower()
    mime_type = VIDEO_MIME_TYPES.get(suffix, "video/mp4")
    if video["size_bytes"] <= HOVER_PREVIEW_MAX_BYTES:
        encoded_video = base64.b64encode(video["content"]).decode("ascii")
        media_html = f"""
          <video muted loop playsinline preload="metadata"
            ontimeupdate="if(this.currentTime >= 8){{this.currentTime=0; this.play()}}">
            <source src="data:{mime_type};base64,{encoded_video}" type="{mime_type}">
          </video>
          <div class="hint">▶ 미리보기</div>
        """
    else:
        media_html = """
          <div class="large-video"><strong>대용량 영상</strong><br><small>분석 화면에서 재생됩니다</small></div>
        """

    # 카드 전체가 하나의 클릭 영역이다. 마우스를 올리면 미리보기가 재생되고, 카드 어디를
    # 클릭해도 화면에 보이지 않는 Streamlit 버튼(open-card-N)을 눌러 상태 전환을 일으킨다.
    # 터치 기기에서는 첫 탭이 미리보기를 재생하고, 재생 중 다시 탭하면 분석 화면으로 이동한다.
    render_html_frame(
        f"""
        <style>
          * {{ box-sizing:border-box; }}
          html, body {{ margin:0; padding:3px 1px 6px; background:transparent; overflow:hidden;
                        font-family:'Noto Sans KR',Arial,sans-serif; }}
          .card {{ padding:14px; border:1px solid #dbe3ef; border-radius:10px; background:#fff;
                   cursor:pointer; outline:none; user-select:none;
                   transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease; }}
          .card:hover, .card:focus-visible, .card.playing {{ transform:translateY(-2px); border-color:#93b4ff;
                   box-shadow:0 10px 24px rgba(30,64,175,.13); }}
          .card:focus-visible {{ border-color:#1d4ed8; }}
          .preview {{ position:relative; width:100%; aspect-ratio:16/9; border-radius:7px; overflow:hidden; background:#0f172a; }}
          video {{ width:100%; height:100%; object-fit:cover; display:block; pointer-events:none; }}
          .large-video {{ position:absolute; inset:0; display:grid; place-content:center; text-align:center; color:#94a3b8;
                          background:linear-gradient(145deg,#142238,#22344e); line-height:1.6; font-size:13px; }}
          .hint {{ position:absolute; left:10px; bottom:10px; padding:5px 8px; border-radius:4px;
                   background:rgba(15,23,42,.76); color:#e2e8f0; font:600 10px monospace;
                   pointer-events:none; transition:opacity .18s ease; }}
          .card:hover .hint, .card.playing .hint {{ opacity:0; }}
          .title {{ height:46px; display:flex; align-items:center; margin-top:10px; color:#0f172a;
                    font-size:13px; font-weight:700; line-height:1.3; overflow:hidden; word-break:break-all; }}
          .meta {{ display:flex; justify-content:space-between; align-items:center; margin-top:5px; color:#64748b; font:600 10px monospace; }}
          .status {{ color:#047857; background:#ecfdf5; padding:3px 7px; border-radius:999px; }}
          .status.queued {{ color:#1e40af; background:#dbeafe; }}
        </style>
        <div class="card" role="link" tabindex="0" aria-label="CAM_{index + 1:02d} {safe_name} 분석 화면 열기">
          <div class="preview">{media_html}</div>
          <div class="title">CAM_{index + 1:02d} · {safe_name}</div>
          <div class="meta"><span>{size_mb:.1f} MB</span>
            <span class="status{' queued' if video['status'] == 'queued' else ''}">{status}</span></div>
        </div>
        <script>
          const card = document.querySelector('.card');
          const video = document.querySelector('video');
          const touchOnly = window.matchMedia('(hover: none)').matches;
          const play = () => {{
            if (!video) return;
            card.classList.add('playing');
            video.play().catch(() => {{}});
          }};
          const stop = () => {{
            card.classList.remove('playing');
            if (video) {{ video.pause(); video.currentTime = 0; }}
          }};
          const openAnalysis = () => {{
            const target = window.parent.document.querySelector('.st-key-open-card-{index} button');
            if (target) target.click();
          }};
          // 터치 기기는 탭할 때 mouseenter도 함께 발생하므로 hover 재생은 마우스 환경에서만 연결한다.
          if (!touchOnly) {{
            card.addEventListener('mouseenter', play);
            card.addEventListener('mouseleave', stop);
          }}
          card.addEventListener('click', () => {{
            if (touchOnly && video && !card.classList.contains('playing')) {{ play(); return; }}
            openAnalysis();
          }});
          card.addEventListener('keydown', event => {{
            if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); openAnalysis(); }}
          }});
        </script>
        """,
        fallback_height=300,
    )
    st.button(
        f"CAM_{index + 1:02d} 분석 화면 열기",
        key=f"open-card-{index}",
        on_click=open_analysis,
        args=(index,),
    )


def render_video_gallery() -> None:
    videos = st.session_state.uploaded_videos
    if not videos:
        return

    st.markdown(
        f'<div class="channel-head"><div><div class="section-kicker">VIDEO CHANNELS</div>'
        f'<strong>접수 영상</strong></div><span class="channel-count">{len(videos)} / 5</span></div>',
        unsafe_allow_html=True,
    )
    for row_start in range(0, len(videos), 3):
        columns = st.columns(3, gap="medium")
        for offset, column in enumerate(columns):
            index = row_start + offset
            if index >= len(videos):
                continue
            video = videos[index]
            with column:
                render_video_card(video, index)


def render_upload() -> None:
    st.markdown('<div class="section-kicker">01 · VIDEO INTAKE</div>', unsafe_allow_html=True)
    st.markdown("### 새 영상 접수")
    left, right = st.columns([1.45, 0.55], gap="large")
    with left:
        with st.form("upload_form", clear_on_submit=False):
            uploaded = st.file_uploader(
                "분석할 CCTV 영상을 선택하세요 · 최대 5개",
                type=["mp4", "mov", "avi", "mkv"],
                accept_multiple_files=True,
                help="현재 화면에서는 로컬 미리보기만 제공합니다. API 연결 후 서버로 전송됩니다.",
            )
            camera_id = st.text_input("카메라 ID (선택)", placeholder="예: parking-lot-01")
            submitted = st.form_submit_button("영상 접수", use_container_width=True)
            if submitted:
                if not uploaded:
                    st.error("먼저 영상 파일을 선택해 주세요.")
                elif len(uploaded) > 5:
                    st.error(f"영상은 한 번에 최대 5개까지 접수할 수 있습니다. 현재 {len(uploaded)}개를 선택했습니다.")
                else:
                    st.session_state.uploaded_videos = [
                        {
                            "name": video.name,
                            "content": video.getvalue(),
                            "size_bytes": video.size,
                            "camera_id": camera_id.strip() or None,
                            "status": "ready",
                            "request_key": str(uuid4()),
                        }
                        for video in uploaded
                    ]
                    st.session_state.selected_upload_index = 0
                    st.session_state.analysis_requested = False
                    st.session_state.request_key = str(uuid4())
                    st.success(f"영상 {len(uploaded)}개의 접수 준비가 완료되었습니다.")

    with right:
        st.markdown("""<div class="panel"><div class="section-kicker">ANALYSIS FLOW</div>
        <h4>접수 → 분석 요청 → 검토</h4><p>접수와 분석 시작을 분리해 중복 작업 생성을 방지합니다.</p>
        <p class="mono" style="font-size:.7rem;color:#64748b">X3D-S → YOLO11s → VLM → RAG → REPORT</p></div>""", unsafe_allow_html=True)
        st.info("각 영상 카드를 선택하면 해당 영상의 분석 워크스페이스로 이동합니다.")

    render_video_gallery()


def render_job_summary(result: dict[str, Any]) -> None:
    candidate_count = len(result["candidates"])
    coverage = result["coverage"]
    st.markdown(
        f"""<div class="job-compact"><div><div class="section-kicker">ANALYSIS JOB</div>
        <div class="job-meta">{result['job_id']}</div></div>
        <div><span class="status-chip">{STATUS_LABELS[result['status']]}</span>
        <span class="demo-chip">DEMO</span></div></div>
        <div class="job-facts">의심 후보 <strong>{candidate_count}건</strong> &nbsp;·&nbsp;
        처리 <strong>{coverage['predicted_windows']} / {coverage['scheduled_windows']}</strong></div>""",
        unsafe_allow_html=True,
    )
    level, message = status_message(result)
    getattr(st, level)(message)


def render_metrics(result: dict[str, Any]) -> None:
    coverage = result["coverage"]
    metrics = [
        ("처리 범위", f"{coverage['predicted_windows']} / {coverage['scheduled_windows']}"),
        ("의심 후보", f"{len(result['candidates'])}건"),
        ("미분류", f"{coverage['unclassified_windows']}구간"),
        ("영상 길이", f"{result['video']['duration_seconds']:.1f}초"),
    ]
    metric_html = "".join(
        f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>'
        for label, value in metrics
    )
    st.markdown(f'<div class="metrics-grid">{metric_html}</div>', unsafe_allow_html=True)
    st.caption(f"{result['job_id']} · {result['run_id']}")


def render_stages(result: dict[str, Any]) -> None:
    st.markdown("#### 분석 단계")
    rows = []
    for stage, detail in result["stages"].items():
        state = detail["status"]
        reason = detail.get("reason_code")
        state_text = state.replace("_", " ")
        if reason:
            state_text = f"{state_text} · {reason}"
        rows.append(
            f'<div class="stage"><span>{STAGE_LABELS.get(stage, stage)}</span>'
            f'<span class="stage-state">{STAGE_ICONS.get(state, "○")} {state_text}</span></div>'
        )
    st.markdown(f'<div class="panel">{"".join(rows)}</div>', unsafe_allow_html=True)


def render_coverage(result: dict[str, Any]) -> None:
    coverage = result["coverage"]
    st.markdown("#### 처리 범위")
    scheduled = coverage["scheduled_windows"]
    completed = coverage["predicted_windows"]
    if scheduled:
        st.progress(completed / scheduled, text=f"판정 완료 {completed} / 예정 {scheduled} 구간")
    if coverage["pending_windows"]:
        st.caption(f"대기 중: {coverage['pending_windows']}구간")
    for unknown_range in coverage["unknown_ranges"]:
        st.warning(
            f"{unknown_range['start_seconds']:.1f}–{unknown_range['end_seconds']:.1f}초 · "
            f"{unknown_range['reason_code']}"
        )


def render_video_console(candidate: dict[str, Any] | None, result: dict[str, Any]) -> None:
    duration = result["video"]["duration_seconds"]
    processed = result["coverage"]["predicted_windows"]
    scheduled = result["coverage"]["scheduled_windows"]
    fill = processed / scheduled * 100 if scheduled else 0
    uploaded_videos = st.session_state.uploaded_videos
    if uploaded_videos:
        selected_index = min(st.session_state.selected_upload_index, len(uploaded_videos) - 1)
        selected_video = uploaded_videos[selected_index]
        video_name = escape(selected_video["name"])
        video_content = selected_video["content"]
    else:
        video_name = "DEMO VIDEO · 실제 영상 없음"
        video_content = None

    if candidate:
        start = candidate["start_seconds"]
        end = candidate["end_seconds"]
        marker_position = min(98.0, max(0.0, start / duration * 100)) if duration else 0.0
        marker_html = f'<div class="candidate-marker" style="left:{marker_position:.1f}%"></div>'
        range_text = f"후보 {start:.1f}–{end:.1f}s &nbsp; | &nbsp; 전체 {duration:.1f}s"
    else:
        start = 0.0
        marker_html = ""
        range_text = f"전체 {duration:.1f}s"

    st.markdown(
        f"""<div class="video-shell"><div class="video-header"><span><span class="video-live">ANALYSIS</span>
        {video_name}</span><span>{duration:.1f}s · UPLOAD FILE</span></div>""",
        unsafe_allow_html=True,
    )
    if video_content:
        st.video(video_content, start_time=int(start))
    else:
        st.markdown(
            """<div class="video-empty"><div><div style="font-size:2.2rem">▻</div>
            <strong>영상 자산 미연결</strong><br><small>영상 접수 탭에서 파일을 업로드하면 이 영역에서 재생됩니다.</small></div></div>""",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""<div class="video-footer"><span>0.0s</span>
        <div class="timeline"><div class="timeline-fill" style="width:{fill:.1f}%"></div>
        {marker_html}</div>
        <span>{range_text}</span></div></div>""",
        unsafe_allow_html=True,
    )
    if candidate:
        st.markdown(
            f"""<div class="evidence-card"><strong>사고 의심 후보 · {start:.1f}–{end:.1f}초</strong>
            <span class="score" style="float:right">MODEL SCORE {candidate['score']:.2f}</span><br>
            <small>이 값은 후보 선별 점수이며 보정된 사고 확률이나 확정 판정이 아닙니다.</small></div>""",
            unsafe_allow_html=True,
        )


def render_ai_analysis(candidate: dict[str, Any]) -> None:
    vlm = candidate["vlm"]
    st.markdown('<div class="section-kicker">VLM SCENE ANALYSIS</div>', unsafe_allow_html=True)
    if vlm["status"] == "running":
        st.info("후보 장면 설명을 생성하고 있습니다.")
    elif vlm["status"] == "failed":
        st.error("장면 설명 생성에 실패했습니다. 영상과 후보 구간은 계속 검토할 수 있습니다.")
    else:
        st.markdown(
            f'<div class="analysis-box"><span class="analysis-label">AI 분석 요약</span>'
            f'<p>{vlm.get("summary") or "생성된 설명이 없습니다."}</p></div>',
            unsafe_allow_html=True,
        )
    for uncertainty in vlm.get("uncertainties", []):
        st.warning(f"불확실성 · {uncertainty}")


def render_review_form(candidate: dict[str, Any], result: dict[str, Any]) -> None:
    event_id = candidate["event_id"]
    st.markdown('<div class="section-kicker">HUMAN REVIEW</div>', unsafe_allow_html=True)
    saved = st.session_state.review_by_event.get(event_id)
    if saved:
        st.success(f"저장된 판단: {saved['decision_label']}")

    with st.form(f"review-{event_id}"):
        decision = st.radio(
            "검토자 최종 판단",
            options=["confirmed_accident", "not_accident", "uncertain"],
            format_func={
                "confirmed_accident": "사고로 확인",
                "not_accident": "사고 아님",
                "uncertain": "판단 보류",
            }.get,
            horizontal=True,
            help="모델 결과와 실제 영상을 함께 확인한 뒤 판단해 주세요.",
        )
        note = st.text_area("검토 메모", placeholder="판단 근거 또는 추가 확인 사항", height=80)
        if st.form_submit_button("검토 결과 저장", type="primary", use_container_width=True):
            labels = {
                "confirmed_accident": "사고로 확인",
                "not_accident": "사고 아님",
                "uncertain": "판단 보류",
            }
            st.session_state.review_by_event[event_id] = {
                "decision": decision,
                "decision_label": labels[decision],
                "note": note.strip(),
                "run_id": result["run_id"],
                "report_revision": candidate["report"].get("revision"),
            }
            st.success("데모 세션에 검토 결과를 저장했습니다.")


def render_report(candidate: dict[str, Any]) -> None:
    report = candidate["report"]
    if report["status"] == "pending":
        st.info("보고 초안을 준비하고 있습니다.")
    else:
        st.markdown(f'<div class="analysis-box"><p>{report.get("text") or "보고 내용이 없습니다."}</p></div>', unsafe_allow_html=True)
        for limitation in report.get("limitations", []):
            st.caption(f"제한사항 · {limitation}")


def render_retrieval(candidate: dict[str, Any]) -> None:
    retrieval = candidate["retrieval"]
    if retrieval["status"] == "insufficient_evidence":
        st.markdown(
            '<div class="rag-item"><strong>문서 근거 부족</strong><br><small>관련성이 충분한 자료를 찾지 못했습니다. 검색 장애를 의미하지 않습니다.</small></div>',
            unsafe_allow_html=True,
        )
    elif retrieval["status"] in {"pending", "running"}:
        st.info("관련 문서 근거를 검색하고 있습니다.")
    elif retrieval["status"] == "skipped":
        st.caption("이 작업에서는 문서 검색 단계를 수행하지 않았습니다.")
    else:
        citations = retrieval.get("citations", [])
        st.success(f"관련 근거 {len(citations)}건을 찾았습니다.")


def render_pipeline(result: dict[str, Any]) -> None:
    render_metrics(result)
    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        render_coverage(result)
    with right:
        render_stages(result)
    for error in result["errors"]:
        retry = "재시도 가능" if error["retryable"] else "재시도 불가"
        st.error(f"{error['stage']} · {error['message']} · {retry}")


def select_candidate(result: dict[str, Any]) -> dict[str, Any] | None:
    if not result["candidates"]:
        return None
    candidate_labels = {
        item["event_id"]: f"{item['start_seconds']:.1f}–{item['end_seconds']:.1f}초 · 점수 {item['score']:.2f}"
        for item in result["candidates"]
    }
    selected_event_id = st.selectbox(
        "검토할 사고 의심 후보",
        options=list(candidate_labels),
        format_func=lambda value: candidate_labels.get(value, value),
    )
    return next(item for item in result["candidates"] if item["event_id"] == selected_event_id)


def render_result(result: dict[str, Any]) -> None:
    # 영상을 첫 화면 상단에 크게 두고, 검토에 바로 필요한 정보만 오른쪽에 둔다.
    video_column, side_column = st.columns([7.4, 4.6], gap="medium")
    with side_column:
        render_job_summary(result)
        candidate = select_candidate(result)
        if candidate:
            render_ai_analysis(candidate)
            render_review_form(candidate, result)
        elif result["detection_outcome"] == "no_candidates":
            st.success("분석된 범위에서 사고 의심 후보가 없습니다.")
        else:
            st.info("현재 표시할 사고 의심 후보가 없습니다.")
    with video_column:
        render_video_console(candidate, result)

    # 보고서, 문서 근거, 처리 상세는 영상 아래 탭으로 내린다.
    st.markdown('<div style="height:.6rem"></div>', unsafe_allow_html=True)
    pipeline_label = "처리 현황" + (f" · 오류 {len(result['errors'])}" if result["errors"] else "")
    if candidate:
        report_tab, retrieval_tab, pipeline_tab = st.tabs(["AI 사고 분석 보고서", "유사 사례 및 문서 근거", pipeline_label])
        with report_tab:
            render_report(candidate)
        with retrieval_tab:
            render_retrieval(candidate)
    else:
        (pipeline_tab,) = st.tabs([pipeline_label])
    with pipeline_tab:
        render_pipeline(result)


def main() -> None:
    st.set_page_config(
        page_title="Road Watch · 사고 의심 분석",
        page_icon="🚦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()
    cases = load_demo_cases()
    initialize_state(cases)
    selected_result = render_sidebar(cases)

    st.markdown("""<div class="topbar"><div class="brand"><div class="brand-mark">AI</div><div>
    <div class="brand-title">AegisTraffic AI</div><div class="brand-sub">교통사고 영상 분석 및 검토 플랫폼</div></div></div>
    <div class="system-state">● UI READY &nbsp;·&nbsp; API DEMO &nbsp;·&nbsp; GPU OFFLINE</div>
    <div class="demo-state">DEMO MODE</div></div>""", unsafe_allow_html=True)
    page = st.session_state.current_page
    if page == "intake":
        st.markdown("""<div class="workspace-title"><h1>업로드 영상 사고 의심 분석</h1>
        <p>영상을 시간순으로 분석하고 후보 장면, AI 설명, 문서 근거와 사람의 최종 판단을 함께 관리합니다.</p></div>""", unsafe_allow_html=True)
        render_upload()
    else:
        toolbar_left, toolbar_right = st.columns([0.72, 0.28], vertical_alignment="center")
        with toolbar_left:
            st.button(
                "← 접수 영상 목록으로",
                key="back-to-intake",
                on_click=navigate_to,
                args=("intake",),
            )
        if st.session_state.uploaded_videos:
            active_video = st.session_state.uploaded_videos[st.session_state.selected_upload_index]
            with toolbar_right:
                st.caption(
                    f"선택 영상 {st.session_state.selected_upload_index + 1}/{len(st.session_state.uploaded_videos)}"
                    f" · {active_video['name']}"
                )
        render_result(selected_result)
        with st.expander("데모 화면 상태 변경", expanded=False):
            labels = {
                case["job_id"]: f"{STATUS_LABELS[case['status']]} · {case['job_id'].removeprefix('demo-job-')}"
                for case in cases
            }
            st.selectbox(
                "가상 분석 응답",
                options=list(labels),
                format_func=lambda value: labels.get(value, value),
                key="selected_job_id",
                help="백엔드 연결 전 상태별 화면 검증에만 사용합니다.",
            )


if __name__ == "__main__":
    main()
