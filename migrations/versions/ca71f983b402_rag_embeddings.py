"""Store versioned RAG chunks and their 768-dimensional embeddings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from services.backend.vector_type import Vector768

revision = "ca71f983b402"
down_revision = "a4c193f5d8e1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("rag_corpora",
        sa.Column("corpus_version", sa.String(64), primary_key=True),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_version", sa.String(80), nullable=False),
        sa.Column("index_sha256", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("dimensions = 768", name="ck_rag_dimensions"),
    )
    op.create_table("rag_chunks",
        sa.Column("corpus_version", sa.String(64), sa.ForeignKey("rag_corpora.corpus_version"), primary_key=True),
        sa.Column("chunk_id", sa.String(255), primary_key=True),
        sa.Column("document_id", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("embedding", Vector768(), nullable=False),
    )


def downgrade():
    op.drop_table("rag_chunks")
    op.drop_table("rag_corpora")
    # The vector extension can also be used by other tables; retain it.
