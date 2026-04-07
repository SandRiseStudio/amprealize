export const PERSONAL_SCOPE_LABEL = 'Personal';
export const ORGANIZATION_SCOPE_LABEL = 'Organization';
export const CURRENT_SCOPE_LABEL = 'Current Scope';
export const SCOPE_LABEL = 'Scope';
export const SCOPE_ACCESS_LABEL = 'Scope access';
export const MANAGE_SCOPES_CTA = 'Manage scopes';
export const CREATE_PROJECT_CTA = 'Create Project';
export const NEW_PROJECT_CTA = 'New Project';
export const CREATE_ORGANIZATION_CTA = 'Create Organization';

export const PERSONAL_SCOPE_DESCRIPTION = 'Projects you own outside any organization.';
export const PERSONAL_SCOPE_SUBTITLE = 'Your default space for projects, agents, and runs.';
export const ORGANIZATION_SCOPE_DESCRIPTION = 'Shared projects, agents, and membership controls.';
export const PERSONAL_SCOPE_SHORT_HINT = 'Switch to personal';
export const PERSONAL_SCOPE_SELECTED_HINT = 'Selected';

export function resolveScopeLabel(scopeName?: string | null): string {
  return scopeName?.trim() || PERSONAL_SCOPE_LABEL;
}

export function describeSharedScope(scopeName?: string | null): string {
  return scopeName?.trim() || ORGANIZATION_SCOPE_LABEL;
}

export function resolveScopeSubtitle(scopeName?: string | null): string {
  return scopeName?.trim() ? ORGANIZATION_SCOPE_DESCRIPTION : PERSONAL_SCOPE_SUBTITLE;
}
