"""Import precomputed embeddings atomically into PostgreSQL; no Gemini calls."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path


def prepare(corpus_path, index_path):
    corpus_bytes, index_bytes = corpus_path.read_bytes(), index_path.read_bytes()
    digest = hashlib.sha256(corpus_bytes).hexdigest()
    index = json.loads(index_bytes)
    if (index["corpus_sha256"] != digest or index["dimensions"] != 768
            or index["model"] != "gemini-embedding-001" or index["input_version"] != "embedding-input-v1"):
        raise ValueError("embedding_index_configuration_mismatch")
    rows, seen = [], set()
    for line in corpus_bytes.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["chunk_id"] in seen:
            raise ValueError("duplicate_chunk_id")
        seen.add(row["chunk_id"])
        if hashlib.sha256(row["content"].encode()).hexdigest() != row["content_sha256"]:
            raise ValueError("content_hash_mismatch")
        if row["corpus_kind"] != "statistics":
            rows.append(row)
    if set(index["vectors"]) != {row["chunk_id"] for row in rows}:
        raise ValueError("incomplete_embedding_index")
    for vector in index["vectors"].values():
        if (len(vector) != 768 or not all(math.isfinite(value) for value in vector)
                or abs(sum(value * value for value in vector) - 1) > 1e-6):
            raise ValueError("invalid_embedding")
    return rows, index, hashlib.sha256(index_bytes).hexdigest()


def store(connection, rows, index, index_hash):
    from psycopg.types.json import Jsonb

    version = index["corpus_sha256"]
    with connection.transaction():
        connection.execute("""INSERT INTO rag_corpora
            (corpus_version, embedding_model, dimensions, input_version, index_sha256, chunk_count)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (corpus_version) DO NOTHING""",
            (version, index["model"], index["dimensions"], index["input_version"], index_hash, len(rows)))
        saved = connection.execute("""SELECT embedding_model, dimensions, input_version, index_sha256, chunk_count
            FROM rag_corpora WHERE corpus_version=%s FOR UPDATE""", (version,)).fetchone()
        if saved != (index["model"], index["dimensions"], index["input_version"], index_hash, len(rows)):
            raise ValueError("corpus_version_already_has_different_embeddings")
        with connection.cursor() as cursor:
            cursor.executemany("""INSERT INTO rag_chunks
                (corpus_version, chunk_id, document_id, content, content_sha256, payload, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s::vector)
                ON CONFLICT (corpus_version, chunk_id) DO NOTHING""",
                [(version, row["chunk_id"], row["document_id"], row["content"], row["content_sha256"],
                  Jsonb(row), json.dumps(index["vectors"][row["chunk_id"]])) for row in rows])
        count = connection.execute("SELECT count(*) FROM rag_chunks WHERE corpus_version=%s", (version,)).fetchone()[0]
        if count != len(rows):
            raise ValueError("database_chunk_count_mismatch")
    return count


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("data/rag/chunks.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/rag/embeddings.json"))
    args = parser.parse_args()
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        parser.error("A PostgreSQL DATABASE_URL is required")
    rows, index, index_hash = prepare(args.corpus, args.index)
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=10) as connection:
        count = store(connection, rows, index, index_hash)
    print(json.dumps({"stored_chunks": count, "dimensions": 768, "corpus_version": index["corpus_sha256"]}))


if __name__ == "__main__":
    main()
