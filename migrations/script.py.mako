"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Behavior: behavior_migrate_postgres_schema

IMPORTANT - Common Pitfalls to Avoid:
1. down_revision must match an ACTUAL revision ID (not a filename)
2. Run 'alembic heads' before committing - must show single head
3. create_index() does NOT support 'comment' parameter - use Python comments
4. For merge migrations, use: alembic merge -m 'description' head1 head2
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Apply migration."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert migration."""
    ${downgrades if downgrades else "pass"}
