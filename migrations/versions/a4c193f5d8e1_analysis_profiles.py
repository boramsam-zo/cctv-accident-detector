"""Store selectable analysis model and weight profiles."""

from alembic import op
import sqlalchemy as sa


revision = "a4c193f5d8e1"
down_revision = "71be9cf630b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_profiles",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("analysis_profiles")
