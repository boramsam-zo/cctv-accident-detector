"""Store Modal function call IDs for asynchronous inference."""

from alembic import op
import sqlalchemy as sa


revision = "71be9cf630b7"
down_revision = "ff248288394e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the durable Modal job handle to each run."""
    op.add_column("runs", sa.Column("modal_call_id", sa.String(length=120), nullable=True))
    op.create_index("ix_runs_modal_call_id", "runs", ["modal_call_id"], unique=True)


def downgrade() -> None:
    """Remove Modal job handles."""
    op.drop_index("ix_runs_modal_call_id", table_name="runs")
    op.drop_column("runs", "modal_call_id")
