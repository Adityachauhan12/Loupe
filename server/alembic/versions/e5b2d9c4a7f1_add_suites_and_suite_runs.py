"""add suites, suite_traces, suite_runs (v2.2 Prompt CI/CD)

Golden suites of saved traces + per-run scoring results.
- suites: a named collection of traces, with an optional per-suite judge rubric.
- suite_traces: join table (B8.1 — suites store traces by reference, not by copy).
- suite_runs: one execution of a suite vs a new prompt; per-trace verdicts in a
  single JSONB `results` column (B8.2). See ARCHITECTURE_DECISIONS.md B8.

Revision ID: e5b2d9c4a7f1
Revises: d4a1c2e3f5b6
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = 'e5b2d9c4a7f1'
down_revision: Union[str, None] = 'd4a1c2e3f5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suites',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('judge_rubric', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_suites_project', 'suites', ['project_id'])

    op.create_table(
        'suite_traces',
        sa.Column('suite_id', UUID(as_uuid=True), nullable=False),
        sa.Column('trace_id', UUID(as_uuid=True), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['suite_id'], ['suites.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trace_id'], ['traces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('suite_id', 'trace_id'),
    )
    op.create_index('idx_suite_traces_trace', 'suite_traces', ['trace_id'])

    op.create_table(
        'suite_runs',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('suite_id', UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='running', nullable=False),
        sa.Column('prompt_override', sa.Text(), nullable=True),
        sa.Column('model_override', sa.Text(), nullable=True),
        sa.Column('judge_backend', sa.Text(), nullable=True),
        sa.Column('total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('passed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('regressed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('improved', sa.Integer(), server_default='0', nullable=False),
        sa.Column('errored', sa.Integer(), server_default='0', nullable=False),
        sa.Column('results', JSONB(), nullable=True),
        sa.Column('error', JSONB(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['suite_id'], ['suites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_suite_runs_suite', 'suite_runs', ['suite_id'])


def downgrade() -> None:
    op.drop_index('idx_suite_runs_suite', table_name='suite_runs')
    op.drop_table('suite_runs')
    op.drop_index('idx_suite_traces_trace', table_name='suite_traces')
    op.drop_table('suite_traces')
    op.drop_index('idx_suites_project', table_name='suites')
    op.drop_table('suites')
