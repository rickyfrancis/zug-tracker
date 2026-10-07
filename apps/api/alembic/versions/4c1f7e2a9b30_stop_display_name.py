"""stop display name

Adds ``stop.display_name``: the name to show for a station, chosen at import
from its platforms' names (``S+U Berlin Hauptbahnhof`` -> ``Berlin Hbf``).

Nullable, and not backfilled: datasets imported before this revision keep
showing the parent station's own name until the next import, which the timetable
read falls back to. ``make import-data force=1`` re-imports immediately.

Revision ID: 4c1f7e2a9b30
Revises: 736d3a81c9d5
Create Date: 2026-10-06 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c1f7e2a9b30"
down_revision: str | Sequence[str] | None = "736d3a81c9d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stop", sa.Column("display_name", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("stop", "display_name")
