# Database Migration Guide

Behavior: `behavior_migrate_postgres_schema`

This guide covers best practices for creating and managing Alembic migrations in Amprealize.

## Quick Start

```bash
# Create a new migration
alembic revision -m "add_new_table"

# Check migration chain is valid
python scripts/validate_migrations.py

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## ⚠️ Common Pitfalls to Avoid

These issues have caused past migration failures:

### 1. Revision ID Mismatch

**Problem**: Using the filename as the `down_revision` instead of the actual revision ID.

```python
# ❌ WRONG - using filename
down_revision = "20260115_add_user_github_links"

# ✅ CORRECT - using actual revision ID from that file
down_revision = "add_user_github_links"
```

**How to check**: Look at the target migration's `revision: str = "..."` line.

### 2. Multiple Heads (Branching)

**Problem**: Two migrations both depend on the same parent, creating parallel branches.

```
       ┌── migration_a (head)
parent ┤
       └── migration_b (head)  ← Multiple heads!
```

**How to fix**:
```bash
# Check for multiple heads
alembic heads

# If multiple heads exist, create a merge migration
alembic merge -m "merge_branches" head1_rev head2_rev
```

**Prevention**: Always check `alembic heads` before committing. Should show only ONE head.

### 3. Unsupported Parameters

**Problem**: Using parameters that Alembic/SQLAlchemy don't support.

```python
# ❌ WRONG - 'comment' not supported for indexes
op.create_index("idx_foo", "table", ["col"], comment="My comment")

# ✅ CORRECT - use a Python comment instead
# Index for faster lookups on col
op.create_index("idx_foo", "table", ["col"])
```

### 4. Building Off Wrong Parent After Merge

**Problem**: New migration builds off a pre-merge revision instead of the merge point.

```
     ┌── rev_a ──┐
base ┤           ├── merge_point ← New migrations should start HERE
     └── rev_b ──┘
                  └── new_migration ← NOT from rev_a or rev_b
```

**How to check**: Run `alembic current` to see where you are, then `alembic heads` to confirm single head.

## Validation

### Automated Checks

The `validate_migrations.py` script runs automatically via pre-commit:

```bash
# Manual run
python scripts/validate_migrations.py

# Via pre-commit
pre-commit run validate-migrations --all-files
```

Checks performed:
- ✅ All `down_revision` values reference valid revision IDs
- ✅ No unsupported parameters in Alembic operations
- ✅ Single migration head (no unmerged branches)
- ⚠️ Docstring consistency (warning only)

### Pre-Commit Hook

The hook runs on every commit that touches `migrations/versions/*.py`:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: validate-migrations
      name: Validate Alembic Migrations
      entry: python scripts/validate_migrations.py
      language: python
      files: ^migrations/versions/.*\.py$
```

## Best Practices

### 1. Always Check Heads Before Creating Migration

```bash
alembic heads  # Should show exactly ONE head
alembic revision -m "my_new_migration"
```

### 2. Use Descriptive Revision IDs

The template auto-generates revision IDs from the `-m` message. Use clear, action-oriented names:

```bash
# Good
alembic revision -m "add_user_preferences_table"
alembic revision -m "drop_legacy_auth_columns"

# Bad
alembic revision -m "update"
alembic revision -m "fix"
```

### 3. Test Migrations Locally

```bash
# Apply
alembic upgrade head

# Verify
alembic current

# Test rollback
alembic downgrade -1
alembic upgrade head
```

### 4. Include Rollback Logic

Always implement `downgrade()`:

```python
def upgrade() -> None:
    op.create_table("users", ...)

def downgrade() -> None:
    op.drop_table("users")
```

### 5. Handle Data Migrations Carefully

For data migrations, make them idempotent:

```python
def upgrade() -> None:
    # Check if already migrated
    conn = op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM users WHERE migrated = true"))
    if result.scalar() > 0:
        return  # Already migrated

    # Perform migration
    conn.execute(text("UPDATE users SET migrated = true"))
```

## Troubleshooting

### "Multiple head revisions are present"

```bash
# See all heads
alembic heads

# Merge them
alembic merge -m "merge_description" rev1 rev2

# Then upgrade
alembic upgrade head
```

### "Target revision not found"

Your `down_revision` references a revision that doesn't exist. Check:

1. Is the revision ID correct (not the filename)?
2. Did you forget to commit the parent migration?
3. Is there a typo?

### "Revision already applied"

```bash
# Check current state
alembic current

# See full history
alembic history --verbose

# If stuck, stamp to a known state (use carefully!)
alembic stamp <revision>
```

## CI/CD Integration

Migrations are validated in CI via pre-commit. The workflow:

1. `pre-commit run --all-files` runs `validate_migrations.py`
2. If validation fails, CI fails
3. Migrations are applied in staging before production

## Feature Flags Migration (E4)

Goal E4 (previously called Epic E4) introduced a `feature_flags` table via Alembic migration `20260319_add_feature_flags`.

### Applying the Migration

```bash
# Check current head
alembic heads

# Apply
alembic upgrade head

# Verify
alembic current
```

The migration creates:
- Table `feature_flags` with composite PK (`flag_name`, `scope`, `scope_id`)
- Columns: `flag_type` (boolean|percentage|user_list), `enabled`, `percentage` (0-100), `user_list` (TEXT[]), `description`, `metadata_json` (JSONB), `created_at`, `updated_at`
- Indexes: `ix_feature_flags_scope`, `ix_feature_flags_name`

### Rollback

```bash
alembic downgrade 20260318_add_kp_tables
```

## Pack Bootstrap for Existing Workspaces

Existing workspaces without an active knowledge pack can adopt one via the bootstrap workflow:

```bash
# Detect workspace profile and activate a pack
amprealize pack bootstrap --workspace .

# Force re-bootstrap (overwrites existing activation)
amprealize pack bootstrap --workspace . --force

# Specify a profile explicitly
amprealize pack bootstrap --workspace . --profile SOLO_DEV

# Check current status
amprealize pack status --workspace .

# Rollback (deactivate pack, restore pre-pack behavior)
amprealize pack rollback --workspace .
```

The bootstrap process:
1. Detects storage backend (Postgres / SQLite / JSON / Unknown)
2. Detects workspace profile via `WorkspaceDetector`
3. Builds a deterministic pack ID from `AGENTS.md` content hash
4. Activates the pack via `BootstrapService` or `ActivationService`

MCP equivalents: `pack.bootstrap`, `pack.rollback`, `pack.status`.

## Related Documentation

- [AUDIT_LOG_STORAGE.md](./AUDIT_LOG_STORAGE.md) - Storage layer schemas
- [AGENTS.md](../AGENTS.md) - Behavior handbook including `behavior_migrate_postgres_schema`
