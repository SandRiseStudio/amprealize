"""Multi-tenancy support - organizations, RLS, invitations, billing

Revision ID: native_0005_multi_tenancy
Revises: native_0004_services
Create Date: 2025-12-11

Adds multi-tenancy infrastructure including:
- Organizations table with settings
- Organization memberships
- Organization invitations
- Row-level security policies
- Billing records
- Audit logging for org changes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'native_0005_multi_tenancy'
down_revision = 'native_0004_services'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add multi-tenancy support."""

    # =============================================================================
    # Organizations table
    # =============================================================================
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('settings', postgresql.JSONB, server_default='{}'),
        sa.Column('billing_email', sa.String(255)),
        sa.Column('billing_plan', sa.String(50), server_default="'free'"),
        sa.Column('billing_status', sa.String(50), server_default="'active'"),
        sa.Column('stripe_customer_id', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
    )

    op.create_index('idx_organizations_slug', 'organizations', ['slug'])
    op.create_index('idx_organizations_billing_plan', 'organizations', ['billing_plan'])
    op.create_index('idx_organizations_deleted_at', 'organizations', ['deleted_at'])

    # =============================================================================
    # Organization memberships
    # =============================================================================
    op.create_table(
        'organization_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default="'member'"),
        sa.Column('permissions', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_membership_user'),
    )

    op.create_index('idx_org_memberships_org_id', 'organization_memberships', ['organization_id'])
    op.create_index('idx_org_memberships_user_id', 'organization_memberships', ['user_id'])
    op.create_index('idx_org_memberships_role', 'organization_memberships', ['role'])

    # =============================================================================
    # Organization invitations
    # =============================================================================
    op.create_table(
        'organization_invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default="'member'"),
        sa.Column('token', sa.String(255), nullable=False, unique=True),
        sa.Column('invited_by_user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_org_invitations_org_id', 'organization_invitations', ['organization_id'])
    op.create_index('idx_org_invitations_email', 'organization_invitations', ['email'])
    op.create_index('idx_org_invitations_token', 'organization_invitations', ['token'])
    op.create_index('idx_org_invitations_expires', 'organization_invitations', ['expires_at'])

    # =============================================================================
    # Billing records
    # =============================================================================
    op.create_table(
        'billing_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stripe_invoice_id', sa.String(255)),
        sa.Column('stripe_payment_intent_id', sa.String(255)),
        sa.Column('amount_cents', sa.Integer, nullable=False),
        sa.Column('currency', sa.String(3), server_default="'usd'"),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('period_start', sa.DateTime(timezone=True)),
        sa.Column('period_end', sa.DateTime(timezone=True)),
        sa.Column('metadata', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_billing_records_org_id', 'billing_records', ['organization_id'])
    op.create_index('idx_billing_records_status', 'billing_records', ['status'])
    op.create_index('idx_billing_records_created', 'billing_records', ['created_at'])
    op.create_index('idx_billing_records_stripe_invoice', 'billing_records', ['stripe_invoice_id'])

    # =============================================================================
    # Add organization_id to existing tables (with nullable initially)
    # =============================================================================

    # Add to runs table
    op.add_column('runs', sa.Column('organization_id', postgresql.UUID(as_uuid=True)))
    op.create_index('idx_runs_organization_id', 'runs', ['organization_id'])
    op.create_foreign_key('fk_runs_organization', 'runs', 'organizations',
                          ['organization_id'], ['id'], ondelete='SET NULL')

    # Add to behaviors table
    op.add_column('behaviors', sa.Column('organization_id', postgresql.UUID(as_uuid=True)))
    op.create_index('idx_behaviors_organization_id', 'behaviors', ['organization_id'])
    op.create_foreign_key('fk_behaviors_organization', 'behaviors', 'organizations',
                          ['organization_id'], ['id'], ondelete='SET NULL')

    # Add to actions table
    op.add_column('actions', sa.Column('organization_id', postgresql.UUID(as_uuid=True)))
    op.create_index('idx_actions_organization_id', 'actions', ['organization_id'])
    op.create_foreign_key('fk_actions_organization', 'actions', 'organizations',
                          ['organization_id'], ['id'], ondelete='SET NULL')

    # =============================================================================
    # Row-Level Security (RLS) Policies
    # =============================================================================

    # Enable RLS on tables
    op.execute('ALTER TABLE organizations ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organization_invitations ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE billing_records ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE runs ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE behaviors ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE actions ENABLE ROW LEVEL SECURITY')

    # Create RLS policies for organization access
    # Users can see organizations they're members of
    op.execute("""
        CREATE POLICY org_member_access ON organizations
        FOR ALL
        USING (
            id IN (
                SELECT organization_id FROM organization_memberships
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
            )
        )
    """)

    # Users can see their own memberships
    op.execute("""
        CREATE POLICY membership_self_access ON organization_memberships
        FOR ALL
        USING (
            user_id = current_setting('app.current_user_id', true)::uuid
            OR organization_id IN (
                SELECT organization_id FROM organization_memberships
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
                AND role IN ('admin', 'owner')
            )
        )
    """)

    # Runs visible to org members
    op.execute("""
        CREATE POLICY runs_org_access ON runs
        FOR ALL
        USING (
            organization_id IS NULL
            OR organization_id IN (
                SELECT organization_id FROM organization_memberships
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
            )
        )
    """)

    # Behaviors visible to org members
    op.execute("""
        CREATE POLICY behaviors_org_access ON behaviors
        FOR ALL
        USING (
            organization_id IS NULL
            OR organization_id IN (
                SELECT organization_id FROM organization_memberships
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
            )
        )
    """)

    # Actions visible to org members
    op.execute("""
        CREATE POLICY actions_org_access ON actions
        FOR ALL
        USING (
            organization_id IS NULL
            OR organization_id IN (
                SELECT organization_id FROM organization_memberships
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
            )
        )
    """)

    # =============================================================================
    # Organization audit trigger
    # =============================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION log_organization_changes()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO audit_log (entity_type, entity_id, action, new_values, actor_id)
                VALUES ('organization', NEW.id::text, 'create', row_to_json(NEW),
                        current_setting('app.current_user_id', true));
            ELSIF TG_OP = 'UPDATE' THEN
                INSERT INTO audit_log (entity_type, entity_id, action, old_values, new_values, actor_id)
                VALUES ('organization', NEW.id::text, 'update', row_to_json(OLD), row_to_json(NEW),
                        current_setting('app.current_user_id', true));
            ELSIF TG_OP = 'DELETE' THEN
                INSERT INTO audit_log (entity_type, entity_id, action, old_values, actor_id)
                VALUES ('organization', OLD.id::text, 'delete', row_to_json(OLD),
                        current_setting('app.current_user_id', true));
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trg_organization_audit
        AFTER INSERT OR UPDATE OR DELETE ON organizations
        FOR EACH ROW EXECUTE FUNCTION log_organization_changes()
    """)

    # =============================================================================
    # Updated_at trigger for organizations
    # =============================================================================
    op.execute("""
        CREATE TRIGGER trg_organizations_updated_at
        BEFORE UPDATE ON organizations
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)

    op.execute("""
        CREATE TRIGGER trg_org_memberships_updated_at
        BEFORE UPDATE ON organization_memberships
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)


def downgrade() -> None:
    """Remove multi-tenancy support."""

    # Drop triggers
    op.execute('DROP TRIGGER IF EXISTS trg_org_memberships_updated_at ON organization_memberships')
    op.execute('DROP TRIGGER IF EXISTS trg_organizations_updated_at ON organizations')
    op.execute('DROP TRIGGER IF EXISTS trg_organization_audit ON organizations')
    op.execute('DROP FUNCTION IF EXISTS log_organization_changes()')

    # Drop RLS policies
    op.execute('DROP POLICY IF EXISTS actions_org_access ON actions')
    op.execute('DROP POLICY IF EXISTS behaviors_org_access ON behaviors')
    op.execute('DROP POLICY IF EXISTS runs_org_access ON runs')
    op.execute('DROP POLICY IF EXISTS membership_self_access ON organization_memberships')
    op.execute('DROP POLICY IF EXISTS org_member_access ON organizations')

    # Disable RLS
    op.execute('ALTER TABLE actions DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE behaviors DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE runs DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE billing_records DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organization_invitations DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organization_memberships DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organizations DISABLE ROW LEVEL SECURITY')

    # Remove organization_id from existing tables
    op.drop_constraint('fk_actions_organization', 'actions', type_='foreignkey')
    op.drop_index('idx_actions_organization_id', table_name='actions')
    op.drop_column('actions', 'organization_id')

    op.drop_constraint('fk_behaviors_organization', 'behaviors', type_='foreignkey')
    op.drop_index('idx_behaviors_organization_id', table_name='behaviors')
    op.drop_column('behaviors', 'organization_id')

    op.drop_constraint('fk_runs_organization', 'runs', type_='foreignkey')
    op.drop_index('idx_runs_organization_id', table_name='runs')
    op.drop_column('runs', 'organization_id')

    # Drop tables in reverse order
    op.drop_table('billing_records')
    op.drop_table('organization_invitations')
    op.drop_table('organization_memberships')
    op.drop_table('organizations')
