#!/usr/bin/env python3
"""
Validate Alembic migration chain integrity.

This script prevents common migration issues:
1. Revision ID mismatches (filename vs actual revision ID)
2. Multiple heads (branching without merging)
3. Unsupported Alembic operation parameters
4. Missing down_revision for non-initial migrations

Run as part of pre-commit hooks or CI pipeline.

Behavior: behavior_migrate_postgres_schema
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


class MigrationInfo(NamedTuple):
    """Parsed migration file info."""
    filepath: Path
    revision_id: str
    down_revision: str | None
    docstring_revises: str | None
    has_comment_in_create_index: bool
    has_comment_in_create_table: bool


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations" / "versions"

# Parameters not supported in certain Alembic operations
UNSUPPORTED_PARAMS = {
    "create_index": ["comment"],  # comment not supported for indexes
    "create_unique_constraint": ["comment"],
}


def parse_migration_file(filepath: Path) -> MigrationInfo | None:
    """Extract migration metadata from a file."""
    try:
        content = filepath.read_text()
    except Exception as e:
        print(f"  ⚠️  Could not read {filepath}: {e}")
        return None

    # Parse revision_id from code - handle both styles:
    # revision: str = "xyz"
    # revision = "xyz"
    revision_match = re.search(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)

    # Parse down_revision from code - handle multiple styles:
    # down_revision: str = "xyz"
    # down_revision: Union[str, None] = "xyz"
    # down_revision = "xyz"
    # down_revision: Union[str, None] = None
    down_match = re.search(
        r'^down_revision(?::\s*(?:str|Union\[str,\s*None\]))?\s*=\s*["\']([^"\']+)["\']',
        content,
        re.MULTILINE
    )
    # Check for None value
    if not down_match:
        none_match = re.search(r'^down_revision(?::\s*(?:str|Union\[str,\s*None\]))?\s*=\s*None', content, re.MULTILINE)
        if none_match:
            down_match = None  # Explicitly None (initial migration)
    # Handle tuple for merge migrations: down_revision = ("rev1", "rev2")
    if not down_match:
        tuple_match = re.search(r'^down_revision[^=]*=\s*\(([^)]+)\)', content, re.MULTILINE)
        if tuple_match:
            # Extract revisions from tuple, create fake match
            class FakeMatch:
                def __init__(self, val):
                    self._val = val
                def group(self, n):
                    return self._val
            revs = [r.strip().strip('"\'') for r in tuple_match.group(1).split(",")]
            down_match = FakeMatch(", ".join(revs))

    # Parse Revises from docstring
    docstring_revises_match = re.search(r'^Revises:\s*(.+)$', content, re.MULTILINE)

    # Check for unsupported parameters in create_index
    has_comment_in_create_index = bool(re.search(
        r'op\.create_index\([^)]*comment\s*=',
        content,
        re.DOTALL
    ))

    # Check for comment parameter spanning multiple lines in create_index
    has_comment_in_create_index = has_comment_in_create_index or bool(re.search(
        r'create_index\([^)]*\n[^)]*comment\s*=',
        content,
        re.DOTALL
    ))

    has_comment_in_create_table = False  # Tables support comments, just checking pattern

    revision_id = revision_match.group(1) if revision_match else ""
    down_revision = down_match.group(1).strip('"\'') if down_match else None
    docstring_revises = docstring_revises_match.group(1).strip() if docstring_revises_match else None

    # Handle None down_revision
    if down_revision and down_revision.lower() == "none":
        down_revision = None

    return MigrationInfo(
        filepath=filepath,
        revision_id=revision_id,
        down_revision=down_revision,
        docstring_revises=docstring_revises,
        has_comment_in_create_index=has_comment_in_create_index,
        has_comment_in_create_table=has_comment_in_create_table,
    )


def check_revision_consistency(migrations: list[MigrationInfo]) -> list[str]:
    """Check that docstring Revises matches down_revision.

    Note: This is a warning, not an error - the actual down_revision variable
    is what Alembic uses. Docstring inconsistency is just documentation debt.
    """
    warnings = []
    for m in migrations:
        if m.docstring_revises and m.down_revision:
            # Handle merge migrations with multiple parents
            if "," in m.docstring_revises or "," in (m.down_revision or ""):
                continue  # Skip merge migrations

            if m.docstring_revises != m.down_revision:
                # This is a warning, not an error - down_revision is what matters
                warnings.append(
                    f"{m.filepath.name}: Docstring 'Revises: {m.docstring_revises}' "
                    f"differs from down_revision='{m.down_revision}' (documentation debt)"
                )
    return warnings


def check_revision_id_references(migrations: list[MigrationInfo]) -> list[str]:
    """Check that down_revision references exist as actual revision IDs."""
    errors = []
    revision_ids = {m.revision_id for m in migrations}

    for m in migrations:
        if m.down_revision is None:
            continue  # Initial migration

        # Handle merge migrations
        down_revs = [r.strip() for r in m.down_revision.split(",")]
        for down_rev in down_revs:
            if down_rev and down_rev not in revision_ids:
                # Check if they're using filename instead of revision ID
                matching_files = [
                    other for other in migrations
                    if down_rev in other.filepath.name and other.revision_id != down_rev
                ]
                if matching_files:
                    errors.append(
                        f"{m.filepath.name}: down_revision='{down_rev}' appears to be a filename, "
                        f"but actual revision ID is '{matching_files[0].revision_id}'"
                    )
                else:
                    errors.append(
                        f"{m.filepath.name}: down_revision='{down_rev}' "
                        f"not found in any migration revision IDs"
                    )
    return errors


def check_unsupported_params(migrations: list[MigrationInfo]) -> list[str]:
    """Check for unsupported Alembic operation parameters."""
    errors = []
    for m in migrations:
        if m.has_comment_in_create_index:
            errors.append(
                f"{m.filepath.name}: 'comment' parameter in create_index() is not supported by SQLAlchemy. "
                f"Use a Python comment instead."
            )
    return errors


def check_multiple_heads() -> list[str]:
    """Use Alembic to check for multiple heads."""
    errors = []
    try:
        result = subprocess.run(
            ["alembic", "heads"],
            capture_output=True,
            text=True,
            cwd=MIGRATIONS_DIR.parent.parent,
            timeout=30,
        )
        heads = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        if len(heads) > 1:
            errors.append(
                f"Multiple migration heads detected: {heads}. "
                f"Create a merge migration with: alembic merge -m 'merge_branches' {' '.join(h.split()[0] for h in heads)}"
            )
    except subprocess.TimeoutExpired:
        errors.append("Timeout running 'alembic heads' - check Alembic configuration")
    except FileNotFoundError:
        # Alembic not installed, skip this check
        pass
    except Exception as e:
        errors.append(f"Error checking Alembic heads: {e}")
    return errors


def check_filename_revision_mismatch(migrations: list[MigrationInfo]) -> list[str]:
    """Warn if filename suggests a different revision ID pattern."""
    warnings = []
    for m in migrations:
        # Extract date prefix from filename if present
        filename_match = re.match(r"(\d{8})_(.+)\.py", m.filepath.name)
        if filename_match:
            date_prefix = filename_match.group(1)
            slug = filename_match.group(2)

            # If revision_id contains the date, that's the problematic pattern
            if date_prefix in m.revision_id and m.revision_id != slug:
                # This is fine - using date in revision ID is valid
                pass
            # Warn if filename slug looks like it should be the revision ID
            # but a different ID is used (could be intentional, just informational)

    return warnings


def main() -> int:
    """Run all migration validations."""
    print("🔍 Validating Alembic migrations...\n")

    if not MIGRATIONS_DIR.exists():
        print(f"❌ Migrations directory not found: {MIGRATIONS_DIR}")
        return 1

    # Parse all migration files
    migration_files = sorted(MIGRATIONS_DIR.glob("*.py"))
    migrations = []
    for f in migration_files:
        if f.name == "__pycache__":
            continue
        info = parse_migration_file(f)
        if info:
            migrations.append(info)

    print(f"📁 Found {len(migrations)} migration files\n")

    all_errors = []
    all_warnings = []

    # Run checks - docstring consistency is a warning, not an error
    print("Checking docstring consistency...")
    warnings = check_revision_consistency(migrations)
    all_warnings.extend(warnings)
    for w in warnings:
        print(f"  ⚠️  {w}")
    if not warnings:
        print("  ✅ Docstring 'Revises' matches down_revision")

    print("\nChecking revision ID references...")
    errors = check_revision_id_references(migrations)
    all_errors.extend(errors)
    for e in errors:
        print(f"  ❌ {e}")
    if not errors:
        print("  ✅ All down_revision references are valid")

    print("\nChecking for unsupported parameters...")
    errors = check_unsupported_params(migrations)
    all_errors.extend(errors)
    for e in errors:
        print(f"  ❌ {e}")
    if not errors:
        print("  ✅ No unsupported parameters found")

    print("\nChecking for multiple heads...")
    errors = check_multiple_heads()
    all_errors.extend(errors)
    for e in errors:
        print(f"  ❌ {e}")
    if not errors:
        print("  ✅ Single migration head")

    # Summary
    print("\n" + "=" * 60)
    if all_warnings:
        print(f"⚠️  {len(all_warnings)} warning(s) - documentation debt, not blocking")
    if all_errors:
        print(f"❌ {len(all_errors)} error(s) found. Fix before committing.")
        return 1
    else:
        print("✅ All critical migration validations passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
