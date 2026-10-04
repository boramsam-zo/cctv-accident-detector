"""Prepare the local retrieval store without calling Gemini or submitting jobs."""

from pathlib import Path

from services.backend.rag import GeminiRag
from services.backend.settings import Settings


def main():
    settings = Settings.from_env()
    if not settings.rag_enabled:
        print("RAG disabled: skipping retrieval preparation.")
        return
    if settings.rag_store == "postgres" and Path(settings.rag_index_path).is_file():
        import psycopg

        from scripts.import_rag_postgres import prepare, store

        rows, index, index_hash = prepare(
            Path(settings.rag_corpus_path), Path(settings.rag_index_path)
        )
        url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=10) as connection:
            count = store(connection, rows, index, index_hash)
        print(f"Imported {count} precomputed RAG chunks; no Gemini requests.")
    rag = GeminiRag(None, settings)
    try:
        rows, _, version = rag._index()
        if not rows:
            raise ValueError("empty_rag_corpus")
        print(f"RAG ready: {len(rows)} chunks; corpus={version}; store={settings.rag_store}")
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "RAG is not ready. Obtain data/rag/embeddings.json from the team, "
            "or explicitly run the rag-index Compose service to generate it. "
            "An existing compatible PostgreSQL corpus can also be reused."
        ) from exc
    finally:
        if rag.engine is not None:
            rag.engine.dispose()


if __name__ == "__main__":
    main()
