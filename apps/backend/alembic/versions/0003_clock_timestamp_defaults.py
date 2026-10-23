"""clock_timestamp defaults

Use clock_timestamp() instead of now() so rows inserted in the same transaction keep their order.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("projects", "created_at"),
    ("projects", "updated_at"),
    ("conversations", "created_at"),
    ("conversations", "updated_at"),
    ("messages", "created_at"),
    ("runs", "created_at"),
    ("router_decisions", "created_at"),
    ("tasks", "created_at"),
    ("tasks", "updated_at"),
    ("agent_executions", "started_at"),
    ("file_changes", "created_at"),
    ("check_results", "created_at"),
    ("reviews", "created_at"),
    ("agent_events", "ts"),
    ("llm_calls", "created_at"),
    ("eval_runs", "created_at"),
]


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(table, column, server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(table, column, server_default=sa.text("now()"))
