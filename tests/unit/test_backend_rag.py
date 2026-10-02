import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from services.backend.rag import GeminiRag, ROOT, load_corpus
from services.backend.settings import Settings


def context(tmp_path):
    rows = []
    for key, agency, end in [("police", "경찰", None), ("fire", "소방", None),
                             ("expired", "소방", "2020-01-01")]:
        text = "차량 충돌 사고 현장 안전"
        rows.append({"chunk_id": key, "document_id": key, "content": text,
            "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "embedding_input": text, "corpus_kind": "statute", "title": key,
            "effective_to": end, "source_url": "https://example.org/source",
            "metadata": {"agencies": [agency], "actors": [agency], "application_conditions": []}})
    corpus = tmp_path / "chunks.jsonl"
    corpus.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "model": "gemini-embedding-001", "dimensions": 2, "input_version": "embedding-input-v1",
        "vectors": {row["chunk_id"]: [1, 0] for row in rows}}), encoding="utf-8")
    settings = Settings("", "", None, "", "", "test-model", "", "", 1, 1,
        rag_corpus_path=str(corpus), rag_index_path=str(index), rag_embedding_dimensions=2)
    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1, 0])])
    return GeminiRag(client, settings), client, index


def test_supplied_corpus_integrity_and_statistics_separation():
    rows, digest = load_corpus(ROOT / "data/rag/chunks.jsonl")
    assert len(rows) == 275
    assert all(row["corpus_kind"] != "statistics" for row in rows)
    assert digest == "12cb84612820800131a1ad5c06d10cce0aa2d7d71f347ee4425d82e3de9395cc"


def test_retrieval_embeds_once_excludes_expired_and_balances_agencies(tmp_path):
    rag, client, _ = context(tmp_path)
    result = rag.retrieve({"description": "차량 충돌"}, recorded_at="2026-10-01T16:00:00+00:00")
    assert result["reference_date"] == "2026-10-02"
    assert {c["chunk_id"] for c in result["citations"]} == {"police", "fire"}
    client.models.embed_content.assert_called_once()
    assert client.models.embed_content.call_args.kwargs["config"].task_type == "RETRIEVAL_QUERY"


def test_stale_index_fails_before_paid_request(tmp_path):
    rag, client, index = context(tmp_path)
    value = json.loads(index.read_text())
    value["corpus_sha256"] = "invalid"
    index.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="configuration_mismatch"):
        rag.retrieve({"description": "scene"})
    client.models.embed_content.assert_not_called()


def test_weak_similarity_returns_no_citations(tmp_path):
    rag, client, _ = context(tmp_path)
    client.models.embed_content.return_value.embeddings[0].values = [0, 1]
    assert rag.retrieve({"description": "차량 충돌"})["status"] == "insufficient_evidence"


def test_postgres_search_uses_database_cosine_scores_and_excludes_expired(tmp_path):
    rag, client, _ = context(tmp_path)
    rows, vectors, digest = rag._index()
    rag._index = Mock(return_value=(rows, vectors, digest))
    rag.engine = MagicMock()
    db = rag.engine.connect.return_value.__enter__.return_value
    # File vectors are identical; PostgreSQL's actual scores must take precedence.
    db.execute.return_value.all.return_value = [("police", 0.1), ("fire", 0.8), ("expired", 1.0)]
    result = rag.retrieve({"description": "차량 충돌"}, recorded_at="2026-10-02")
    assert [c["chunk_id"] for c in result["citations"]] == ["fire"]
    assert result["citations"][0]["similarity"] == 0.8
    assert result["retrieval_version"] == "pgvector-bm25-rrf-v1"
    assert "<=>" in str(db.execute.call_args.args[0])
    assert db.execute.call_args.args[1]["version"] == digest
    client.models.embed_content.assert_called_once()


@pytest.mark.parametrize("key,agency", [("invented", "경찰"), ("police", "소방")])
def test_generated_agencies_require_matching_source(tmp_path, key, agency):
    rag, client, _ = context(tmp_path)
    client.models.generate_content.return_value.text = json.dumps({"summary": "장면",
        "limitations": [], "agencies": [{"agency": agency, "role": "지원", "reason": "사고",
            "selection_status": "supported", "conditions_to_confirm": [], "citation_chunk_ids": [key]}]})
    with pytest.raises(ValueError, match="invalid_report_agency_citation"):
        rag.generate_report({}, {}, {"citations": [{"chunk_id": "police", "agencies": ["경찰"]}]}, model="model")


def test_single_report_call_returns_validated_json(tmp_path):
    rag, client, _ = context(tmp_path)
    client.models.generate_content.return_value.text = json.dumps({"summary": "장면",
        "limitations": ["부상 여부 미확인"], "agencies": [{"agency": "경찰", "role": "교통 안전",
            "reason": "차로 점유", "selection_status": "conditional", "conditions_to_confirm": ["현장 확인"],
            "citation_chunk_ids": ["police"]}]})
    report = rag.generate_report({}, {}, {"citations": [{"chunk_id": "police", "agencies": ["경찰"]}]}, model="model")
    assert report["agencies"][0]["selection_status"] == "conditional"
    client.models.generate_content.assert_called_once()


def test_normal_scene_rejects_response_agencies(tmp_path):
    rag, client, _ = context(tmp_path)
    client.models.generate_content.return_value.text = json.dumps({"summary": "정상",
        "limitations": [], "agencies": [{"agency": "경찰", "role": "지원", "reason": "사고",
            "selection_status": "supported", "conditions_to_confirm": [], "citation_chunk_ids": ["police"]}]})
    with pytest.raises(ValueError, match="normal_scene_has_response_agencies"):
        rag.generate_report({"operator_confirmed": False}, {},
                            {"citations": [{"chunk_id": "police", "agencies": ["경찰"]}]}, model="model")


@pytest.mark.parametrize("reference,valid", [("police", True), ("fire", False)])
def test_field_response_items_must_use_the_agencys_selected_citations(tmp_path, reference, valid):
    rag, client, _ = context(tmp_path)
    client.models.generate_content.return_value.text = json.dumps({
        "summary": "차로 점유 관찰", "limitations": [], "agencies": [{
            "agency": "경찰", "role": "교통 안전", "reason": "차로 점유",
            "selection_status": "supported", "conditions_to_confirm": [],
            "citation_chunk_ids": ["police"], "transmission_items": ["차로 점유 관찰; 부상 미확인"],
            "field_response_items": [{"text": "경찰의 현장 안전조치 참고", "citation_chunk_ids": [reference]}]}]})
    retrieval = {"citations": [{"chunk_id": "police", "agencies": ["경찰"]},
                               {"chunk_id": "fire", "agencies": ["소방"]}]}
    if valid:
        report = rag.generate_report({}, {}, retrieval, model="model")
        assert report["agencies"][0]["transmission_items"] == ["차로 점유 관찰; 부상 미확인"]
        assert report["agencies"][0]["field_response_items"][0]["citation_chunk_ids"] == ["police"]
        assert report["prompt_version"] == "agency-report-v2"
    else:
        with pytest.raises(ValueError, match="invalid_field_response_citation"):
            rag.generate_report({}, {}, retrieval, model="model")


def test_report_sdk_wire_json_uses_native_schema_and_keeps_strict_validation(tmp_path):
    import httpx
    from google import genai
    from pydantic import ValidationError

    captured = []
    payload = {"summary": "scene", "agencies": [], "limitations": []}

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {
            "role": "model", "parts": [{"text": json.dumps(payload)}]}}]})

    client = genai.Client(api_key="test", http_options={
        "client_args": {"transport": httpx.MockTransport(respond)}})
    rag, _, _ = context(tmp_path)
    rag.client = client
    try:
        assert rag.generate_report({}, {}, {"citations": []}, model="test-model")["summary"] == "scene"
        config = captured[0]["generationConfig"]
        assert "responseSchema" not in config
        schema = config["responseJsonSchema"]
        assert schema["additionalProperties"] is False
        assert schema["$defs"]["AgencyRecommendation"]["additionalProperties"] is False
        assert "additional_properties" not in json.dumps(config)
        payload["unexpected"] = "reject"
        with pytest.raises(ValidationError):
            rag.generate_report({}, {}, {"citations": []}, model="test-model")
    finally:
        client.close()
