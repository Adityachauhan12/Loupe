"""branch lineage and replay policy

Adds the three columns needed by the v2 replay engine:
  - traces.branched_from_trace_id  (which trace was this branched from?)
  - traces.branched_from_span_id   (at which span was the branch taken?)
  - spans.replay_policy            ('live' or 'dry_run')

Revision ID: c3f8a21d9b04
Revises: b6bf6f6b52ed
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3f8a21d9b04'
down_revision: Union[str, None] = 'b6bf6f6b52ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # traces — lineage columns
    op.add_column('traces',
        sa.Column('branched_from_trace_id', sa.UUID(), nullable=True)
    )
    op.add_column('traces',
        sa.Column('branched_from_span_id', sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'fk_traces_branched_from_trace',
        'traces', 'traces',
        ['branched_from_trace_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_traces_branched_from_span',
        'traces', 'spans',
        ['branched_from_span_id'], ['id'],
    )
    # index for "list all branches of this trace" query
    op.create_index(
        'idx_traces_branched_from',
        'traces',
        ['branched_from_trace_id'],
    )

    # spans — side-effect policy for replay
    op.add_column('spans',
        sa.Column(
            'replay_policy',
            sa.String(length=16),
            server_default='dry_run',
            nullable=False,
        )
    )


def downgrade() -> None:
    op.drop_column('spans', 'replay_policy')

    op.drop_index('idx_traces_branched_from', table_name='traces')
    op.drop_constraint('fk_traces_branched_from_span', 'traces', type_='foreignkey')
    op.drop_constraint('fk_traces_branched_from_trace', 'traces', type_='foreignkey')
    op.drop_column('traces', 'branched_from_span_id')
    op.drop_column('traces', 'branched_from_trace_id')
