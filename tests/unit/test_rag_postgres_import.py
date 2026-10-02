import json
from pathlib import Path

import pytest

from scripts.import_rag_postgres import prepare
from services.backend.db import make_session_factory
from services.backend.models import RagChunk, RagCorpus


ROOT = Path(__file__).resolve().parents[2]


def test_rag_models_allow_existing_sqlite_test_sessions():
    sessions = make_session_factory("sqlite://")
    assert {"rag_corpora", "rag_chunks"} <= set(RagCorpus.metadata.tables)
    with sessions() as db:
        assert db.query(RagChunk).count() == 0


@pytest.mark.parametrize("change", ["digest", "dimension", "missing", "nan"])
def test_import_rejects_invalid_embeddings_before_database_write(tmp_path, change):
    import hashlib

    corpus = tmp_path / "chunks.jsonl"
    row = {"chunk_id": "one", "content": "text", "corpus_kind": "statute",
           "content_sha256": hashlib.sha256(b"text").hexdigest()}
    corpus.write_text(json.dumps(row), encoding="utf-8")
    value = {"corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(), "dimensions": 768,
             "model": "gemini-embedding-001", "input_version": "embedding-input-v1",
             "vectors": {"one": [1.0] + [0.0] * 767}}
    if change == "digest":
        value["corpus_sha256"] = "wrong"
    elif change == "dimension":
        value["dimensions"] = 3
    elif change == "missing":
        value["vectors"] = {}
    else:
        value["vectors"]["one"][0] = float("nan")
    index = tmp_path / "embeddings.json"
    index.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare(corpus, index)
