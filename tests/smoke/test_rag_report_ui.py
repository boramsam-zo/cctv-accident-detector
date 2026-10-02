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


def test_e2e_final_tabs_show_report_json_and_full_download():
    app = AppTest.from_string('''
from apps.streamlit.e2e_test import render_final_reports, render_metrics
result = {"job_id": "job-test", "status": "completed", "candidates": [{"event_id": "event-test",
    "report": {"report_id": "report-test", "status": "completed", "generation_status": "completed", "text": "차로 장애",
        "structured": {"summary": "차로 장애"}, "agencies": [
            {"agency": "경찰", "role": "교통 안전", "reason": "차로 장애",
             "selection_status": "conditional", "conditions_to_confirm": ["현장 위험 확인"],
             "citation_chunk_ids": ["chunk-test"]}]},
    "retrieval": {"status": "completed", "citations": [
        {"chunk_id": "chunk-test", "document_id": "doc-test", "title": "현장 안전", "excerpt": "교통 안전 근거"}]}
}]}
render_metrics(result, 12.3)
render_final_reports(result)
''').run(timeout=20)
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["기관별 최종 리포트", "검색 근거", "리포트 JSON"]
    assert next(m.value for m in app.metric if m.label == "최종 리포트 완료") == "1"
    assert next(m.value for m in app.metric if m.label == "필요 연락 기관") == "1"
    assert any("현장 위험 확인" in c.value for c in app.caption)
    assert any("generation_status" in j.value for j in app.json)
    assert len(app.get("download_button")) == 2
