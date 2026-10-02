from streamlit.testing.v1 import AppTest


def test_report_shows_agency_role_conditions_and_document_evidence():
    app = AppTest.from_string('''
from apps.streamlit.app import render_report, render_retrieval
candidate = {
    "report": {"status": "completed", "report_id": "report-test", "text": "버스 충돌 관찰",
        "limitations": ["탑승자 상태 미확인"], "agencies": [
            {"agency": "소방", "role": "구조·구급", "reason": "구조 수요 확인 필요",
             "selection_status": "conditional", "conditions_to_confirm": ["탑승자 상태 확인"],
             "citation_chunk_ids": ["chunk-test"]}]},
    "retrieval": {"status": "completed", "reference_date": "2026-10-02", "citations": [
        {"chunk_id": "chunk-test", "document_id": "doc-test", "title": "구조 대응자료",
         "section": "제13조", "excerpt": "구조·구급 대응 근거",
         "source_url": "https://www.law.go.kr", "application_conditions": ["위급상황"]}]}
}
render_report(candidate)
render_retrieval(candidate)
''').run(timeout=20)
    assert not app.exception
    assert any("소방" in item.value for item in app.markdown)
    assert any("탑승자 상태 확인" in item.value for item in app.caption)
    assert any("구조·구급 대응 근거" in item.value for item in app.markdown)
    assert len(app.get("download_button")) == 1
