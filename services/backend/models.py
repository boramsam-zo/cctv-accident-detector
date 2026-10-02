from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .vector_type import Vector768


def now() -> datetime:
    """DB 생성·갱신 시각에 사용할 현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(512), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(80), default="video/mp4")
    duration_seconds: Mapped[float | None]
    camera_id: Mapped[str | None] = mapped_column(String(120))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisProfile(Base):
    __tablename__ = "analysis_profiles"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    models: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"))
    active_run_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    profile_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    outcome: Mapped[str] = mapped_column(String(30), default="pending")
    modal_call_id: Mapped[str | None] = mapped_column(String(120))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    manifest_key: Mapped[str | None] = mapped_column(String(512))
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    s3_key: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(30))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(80))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "sequence_number"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    manifest_key: Mapped[str] = mapped_column(String(512))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("event_id", "revision"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    revision: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("event_id", "revision"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    run_id: Mapped[str] = mapped_column(String(80))
    report_revision: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Idempotency(Base):
    __tablename__ = "idempotency"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class RagCorpus(Base):
    __tablename__ = "rag_corpora"
    __table_args__ = (CheckConstraint("dimensions = 768", name="ck_rag_dimensions"),)
    corpus_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding_model: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int] = mapped_column(Integer)
    input_version: Mapped[str] = mapped_column(String(80))
    index_sha256: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    corpus_version: Mapped[str] = mapped_column(ForeignKey("rag_corpora.corpus_version"), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), name="payload")
    embedding: Mapped[list] = mapped_column(Vector768().with_variant(JSON(), "sqlite"))
