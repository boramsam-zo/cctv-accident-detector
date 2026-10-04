import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    s3_bucket: str
    s3_endpoint_url: str | None
    aws_region: str
    gemini_api_key: str
    gemini_model: str
    app_api_key: str
    analysis_profile_id: str
    max_upload_bytes: int
    max_gemini_clip_bytes: int
    modal_app_name: str = "cctv-accident-inference"
    modal_function_name: str = "analyze_video_job"
    modal_environment: str = "dev"
    s3_key_prefix: str = ""
    gemini_models: tuple[str, ...] = ()
    max_model_weight_bytes: int = 512 * 1024 * 1024
    rag_enabled: bool = False
    rag_corpus_path: str = "data/rag/chunks.jsonl"
    rag_index_path: str = "data/rag/embeddings.json"
    rag_embedding_model: str = "gemini-embedding-001"
    rag_embedding_dimensions: int = 768
    rag_top_k: int = 8
    rag_min_similarity: float = 0.35
    rag_store: str = "file"
    rag_corpus_version: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """환경 변수에서 DB, S3, 인증, Gemini 및 용량 제한 설정을 읽는다."""
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        configured_models = tuple(dict.fromkeys(
            model.strip()
            for model in os.getenv("GEMINI_MODELS", "").split(",")
            if model.strip()
        ))
        if gemini_model not in configured_models:
            configured_models = (gemini_model, *configured_models)
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./backend.db"),
            s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            aws_region=os.getenv("AWS_REGION", "ap-northeast-2"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=gemini_model,
            app_api_key=os.getenv("APP_API_KEY", ""),
            analysis_profile_id=os.getenv("ANALYSIS_PROFILE_ID", "received-yolo-x3ds-v1"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))),
            max_gemini_clip_bytes=int(os.getenv("MAX_GEMINI_CLIP_BYTES", str(18 * 1024 * 1024))),
            modal_app_name=os.getenv("MODAL_APP_NAME", "cctv-accident-inference"),
            modal_function_name=os.getenv("MODAL_FUNCTION_NAME", "analyze_video_job"),
            modal_environment=os.getenv("MODAL_ENVIRONMENT", "dev"),
            s3_key_prefix=(os.getenv("S3_KEY_PREFIX", "").strip("/") + "/"
                           if os.getenv("S3_KEY_PREFIX", "").strip("/") else ""),
            gemini_models=configured_models,
            max_model_weight_bytes=int(os.getenv("MAX_MODEL_WEIGHT_BYTES", str(512 * 1024 * 1024))),
            rag_enabled=os.getenv("RAG_ENABLED", "true").lower() in {"true", "1", "yes"},
            rag_corpus_path=os.getenv("RAG_CORPUS_PATH", "data/rag/chunks.jsonl"),
            rag_index_path=os.getenv("RAG_INDEX_PATH", "data/rag/embeddings.json"),
            rag_embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001"),
            rag_embedding_dimensions=int(os.getenv("RAG_EMBEDDING_DIMENSIONS", "768")),
            rag_top_k=int(os.getenv("RAG_TOP_K", "8")),
            rag_min_similarity=float(os.getenv("RAG_MIN_SIMILARITY", "0.35")),
            rag_store=os.getenv("RAG_STORE", "postgres"),
            rag_corpus_version=os.getenv("RAG_CORPUS_VERSION", ""),
        )
