from streamlit.testing.v1 import AppTest


def test_report_shows_agency_role_conditions_and_document_evidence():
    app = AppTest.from_string('''
from apps.streamlit.app import render_report, render_retrieval
candidate = {
    "report": {"status": "completed", "report_id": "report-test", "text": "버스 충돌 관찰",
        "limitations": ["탑승자 상태 미확인"], "agencies": [
            {"agency": "소방", "role": "구조·구급", "reason": "구조 수요 확인 필요",
             "selection_status": "supported", "conditions_to_confirm": ["탑승자 상태 확인"],
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
             "selection_status": "supported", "conditions_to_confirm": ["현장 위험 확인"],
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


def test_agency_cards_show_only_contact_targets_and_group_handoff_and_response():
    app = AppTest.from_string('''
from apps.streamlit.app import render_agency_response
render_agency_response({
    "event_id": "contact-test",
    "report": {"generation_status": "completed", "agencies": [
        {"agency": "警察<test>", "role": "교통 안전", "selection_status": "supported",
         "transmission_items": ["산길 사고 후 불꽃 관찰", "부상 여부 현장 확인 필요"],
         "field_response_items": [{"text": "현장 안전조치와 증거 보존 참고", "citation_chunk_ids": ["police"]}],
         "citation_chunk_ids": ["police"]},
        {"agency": "산림기관", "selection_status": "conditional", "conditions_to_confirm": ["산림 확산 확인"],
         "transmission_items": ["조건부 내용 표시 금지"], "citation_chunk_ids": ["forest"]}]},
    "retrieval": {"citations": [{"chunk_id": "police", "title": "교통사고 조사규칙", "section": "초동조치",
        "excerpt": "검색 근거", "application_conditions": ["경찰공무원의 현장 조치"]}]}
})
''').run(timeout=20)
    assert not app.exception
    text = "\n".join(m.value for m in app.markdown)
    assert "연락 대상" in text and "&lt;test&gt;" in text
    assert "전달 사항" in text and "현장 대응 참고항목" in text
    assert "산길 사고 후 불꽃 관찰" in text
    assert "현장 안전조치와 증거 보존 참고" in text
    assert "산림기관" not in text and "조건부 내용 표시 금지" not in text
    assert any("교통사고 조사규칙" in c.value for c in app.caption)
    assert any("경찰공무원의 현장 조치" in c.value for c in app.caption)


def test_conditional_only_result_does_not_show_agency_cards():
    app = AppTest.from_string('''
from apps.streamlit.app import render_agency_response
render_agency_response({"report": {"generation_status": "completed", "agencies": [
    {"agency": "산림기관", "selection_status": "conditional"}]}})
''').run(timeout=20)
    assert not app.exception
    assert any("연락 대상 기관이 없습니다" in i.value for i in app.info)
    assert not any("agency-card-head" in m.value for m in app.markdown)
