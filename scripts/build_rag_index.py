"""Build document embeddings once; never embed the whole corpus per video."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.backend.rag import load_corpus, normalize, resolve_path


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
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                         http_options=types.HttpOptions(timeout=60000))
    vectors = {}
    for offset in range(0, len(rows), 64):
        batch = rows[offset:offset + 64]
        response = client.models.embed_content(model=args.model,
            contents=[row["embedding_input"] for row in batch],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=args.dimensions))
        if len(response.embeddings or []) != len(batch):
            raise ValueError("invalid_document_embedding_count")
        for row, embedding in zip(batch, response.embeddings):
            vectors[row["chunk_id"]] = normalize(embedding.values, args.dimensions)
        print(f"Indexed {len(vectors)}/{len(rows)} text chunks", flush=True)
    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"corpus_sha256": digest, "model": args.model,
        "dimensions": args.dimensions, "input_version": "embedding-input-v1", "vectors": vectors}), encoding="utf-8")
    temporary.replace(output)


if __name__ == "__main__":
    main()
