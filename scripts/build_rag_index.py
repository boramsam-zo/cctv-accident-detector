"""Build document embeddings once; never embed the whole corpus per video."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.backend.rag import load_corpus, normalize, resolve_path


def embed_batch(client, *, model, contents, config):
    from google.genai.errors import APIError

    for attempt in range(5):
        try:
            return client.models.embed_content(model=model, contents=contents, config=config)
        except APIError as exc:
            if exc.code not in (429, 503) or attempt == 4:
                raise
            delay = min(60, 20 * (attempt + 1))
            details = (exc.details or {}).get("error", {}).get("details", [])
            for detail in details:
                if detail.get("@type", "").endswith("RetryInfo"):
                    delay = min(60, max(delay, float(detail["retryDelay"].rstrip("s")) + 1))
            print(f"Embedding API {exc.code}; retrying after {delay:g}s", flush=True)
            time.sleep(delay)


def save_index(path, metadata, vectors):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({**metadata, "vectors": vectors}), encoding="utf-8")
    temporary.replace(path)


def main():
    from google import genai
    from google.genai import types

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Read configuration without echoing secrets")
    parser.add_argument("--corpus")
    parser.add_argument("--output")
    parser.add_argument("--model")
    parser.add_argument("--dimensions", type=int)
    args = parser.parse_args()
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    args.corpus = args.corpus or os.getenv("RAG_CORPUS_PATH", "data/rag/chunks.jsonl")
    args.output = args.output or os.getenv("RAG_INDEX_PATH", "data/rag/embeddings.json")
    args.model = args.model or os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001")
    args.dimensions = args.dimensions or int(os.getenv("RAG_EMBEDDING_DIMENSIONS", "768"))
    if args.model != "gemini-embedding-001":
        parser.error("This index format uses RETRIEVAL_DOCUMENT with gemini-embedding-001")
    if not os.getenv("GEMINI_API_KEY"):
        parser.error("GEMINI_API_KEY environment variable is required")
    rows, digest = load_corpus(resolve_path(args.corpus))
    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = output.with_suffix(".checkpoint.json")
    metadata = {"corpus_sha256": digest, "model": args.model,
                "dimensions": args.dimensions, "input_version": "embedding-input-v1"}
    vectors = {}
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if any(saved.get(key) != value for key, value in metadata.items()):
            raise ValueError("checkpoint_configuration_mismatch")
        vectors = {key: normalize(value, args.dimensions) for key, value in saved["vectors"].items()}
        if not set(vectors) <= {row["chunk_id"] for row in rows}:
            raise ValueError("checkpoint_chunk_mismatch")
        print(f"Resuming {len(vectors)}/{len(rows)} text chunks", flush=True)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                         http_options=types.HttpOptions(timeout=60000))
    pending = [row for row in rows if row["chunk_id"] not in vectors]
    for offset in range(0, len(pending), 64):
        batch = pending[offset:offset + 64]
        response = embed_batch(client, model=args.model,
            contents=[row["embedding_input"] for row in batch],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=args.dimensions))
        if len(response.embeddings or []) != len(batch):
            raise ValueError("invalid_document_embedding_count")
        for row, embedding in zip(batch, response.embeddings):
            vectors[row["chunk_id"]] = normalize(embedding.values, args.dimensions)
        save_index(checkpoint, metadata, vectors)
        print(f"Indexed {len(vectors)}/{len(rows)} text chunks", flush=True)
    save_index(output, metadata, vectors)


if __name__ == "__main__":
    main()
