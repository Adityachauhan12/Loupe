"""add traces.replay_mode

Stores how a branch was produced — 'server' (dashboard branch, LLM-only preview)
or 'sdk' (loupe.replay, edit propagates). Null for non-branch traces and for older
branches; the dashboard diff infers the kind as a fallback for those. (Arch decision B3.)

Revision ID: d4a1c2e3f5b6
Revises: c3f8a21d9b04
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4a1c2e3f5b6'
down_revision: Union[str, None] = 'c3f8a21d9b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('traces',
        sa.Column('replay_mode', sa.String(length=16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('traces', 'replay_mode')
