/**
 * Amprealize web console authentication types
 *
 * Shared auth types for the web console, matching:
 * - AGENT_AUTH_ARCHITECTURE.md contracts
 * - Extension AuthProvider.ts ActorIdentity model
 * - Cross-surface parity with VS Code and CLI
 *
 * Supports both human users (device flow) and AI agents (client credentials).
 */

// ---------------------------------------------------------------------------
// Core Identity Types (from AGENT_AUTH_ARCHITECTURE.md)
// ---------------------------------------------------------------------------

/** Actor role in the Amprealize system */
export type ActorRole = 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN' | 'OBSERVER';

/** Surface where the actor is operating */
export type ActorSurface = 'WEB' | 'CLI' | 'VSCODE' | 'MCP' | 'API';

/** Type of actor (human or agent) */
export type ActorType = 'human' | 'agent' | 'service';

/** Actor identity model (matches extension AuthProvider.ts) */
export interface ActorIdentity {
  id: string;
  type: ActorType;
  role: ActorRole;
  surface: ActorSurface;
  displayName?: string;
  email?: string;
  avatarUrl?: string;
  /** For agents: the registered service principal ID */
  servicePrincipalId?: string;
  /** Workspace memberships */
  workspaces?: string[];
}

// ---------------------------------------------------------------------------
// Token Types
// ---------------------------------------------------------------------------

export interface AuthTokens {
  accessToken: string;
  refreshToken?: string;
  tokenType: 'Bearer';
  /** Token expiry timestamp (ms since epoch) */
  expiresAt: number;
  /** Granted scopes */
  scopes: string[];
}

export interface AuthSession {
  id: string;
  actor: ActorIdentity;
  tokens: AuthTokens;
  /** When session was created */
  createdAt: number;
  /** Last activity timestamp */
  lastActiveAt: number;
}

// ---------------------------------------------------------------------------
// Device Flow Types (for human users)
// ---------------------------------------------------------------------------

export interface DeviceCodeResponse {
  deviceCode: string;
  userCode: string;
  verificationUri: string;
  verificationUriComplete: string;
  /** Expiry in seconds */
  expiresIn: number;
  /** Polling interval in seconds */
  interval: number;
}

export type DeviceFlowStatus =
  | 'idle'
  | 'pending'      // Waiting for user to authorize
  | 'polling'      // Actively polling for authorization
  | 'authorized'   // User approved
  | 'denied'       // User denied
  | 'expired'      // Device code expired
  | 'error';       // Generic error

export interface DeviceFlowState {
  status: DeviceFlowStatus;
  deviceCode: DeviceCodeResponse | null;
  error: string | null;
  /** Number of poll attempts */
  pollCount: number;
}

// ---------------------------------------------------------------------------
// Client Credentials Types (for AI agents)
// ---------------------------------------------------------------------------

export interface ServicePrincipal {
  id: string;
  name: string;
  clientId: string;
  /** Hashed, never exposed */
  clientSecretHash?: string;
  /** Allowed scopes for this principal */
  allowedScopes: string[];
  /** Rate limit (requests per minute) */
  rateLimit: number;
  createdAt: string;
  createdBy: string;
}

// ---------------------------------------------------------------------------
// Grant & Consent Types (from AGENT_AUTH_ARCHITECTURE.md)
// ---------------------------------------------------------------------------

export type GrantStatus = 'active' | 'expired' | 'revoked' | 'pending';

export interface Grant {
  id: string;
  userId: string;
  agentId: string;
  toolName: string;
  scopes: string[];
  status: GrantStatus;
  expiresAt: string;
  createdAt: string;
  /** Action ID for audit trail */
  actionId?: string;
}

/** Decision from auth.verifyAction */
export type GrantDecision = 'ALLOW' | 'CONSENT_REQUIRED' | 'DENY' | 'MFA_REQUIRED';

export interface VerifyActionResponse {
  decision: GrantDecision;
  /** Signed access token if ALLOW */
  accessToken?: string;
  /** Grant expiry if ALLOW */
  expiresAt?: string;
  /** Consent URL if CONSENT_REQUIRED */
  consentUrl?: string;
  /** Reason if DENY */
  denyReason?: string;
  /** MFA challenge ID if MFA_REQUIRED */
  mfaChallengeId?: string;
  /** Audit ID */
  auditId: string;
}

// ---------------------------------------------------------------------------
// Consent Types (from CONSENT_UX_PROTOTYPE.md)
// ---------------------------------------------------------------------------

export interface ConsentScope {
  name: string;
  displayName: string;
  description: string;
  /** Is this a high-risk scope requiring MFA? */
  highRisk: boolean;
  /** Provider (e.g., 'slack', 'google', 'internal') */
  provider?: string;
}

export interface ConsentRequest {
  id: string;
  agentId: string;
  agentName: string;
  toolName: string;
  scopes: ConsentScope[];
  /** Purpose statement (<160 chars) */
  purpose: string;
  /** Expiration window for grant if approved */
  expirationDays: number;
  /** Timestamp when request was created */
  createdAt: string;
  /** Number of times user has snoozed */
  snoozeCount: number;
  /** Max snoozes allowed (default: 3) */
  maxSnoozes: number;
}

export type ConsentDecision = 'approve' | 'deny' | 'snooze';

export interface ConsentResponse {
  requestId: string;
  decision: ConsentDecision;
  /** If snooze, when to remind (ms from now) */
  snoozeUntil?: number;
  /** Optional user note for audit */
  note?: string;
}

// ---------------------------------------------------------------------------
// Auth Store State
// ---------------------------------------------------------------------------

export interface AuthState {
  /** Is the store initialized (loaded from storage)? */
  initialized: boolean;
  /** Current session (null if not authenticated) */
  session: AuthSession | null;
  /** Device flow state for login */
  deviceFlow: DeviceFlowState;
  /** Pending consent requests */
  pendingConsents: ConsentRequest[];
  /** Is a token refresh in progress? */
  isRefreshing: boolean;
  /** Last auth error */
  error: string | null;
}

export interface AuthActions {
  // Session management
  setSession: (session: AuthSession | null) => void;
  updateTokens: (tokens: AuthTokens) => void;
  clearSession: () => void;

  // Device flow
  startDeviceFlow: () => void;
  setDeviceCode: (code: DeviceCodeResponse) => void;
  setDeviceFlowStatus: (status: DeviceFlowStatus, error?: string) => void;
  incrementPollCount: () => void;
  resetDeviceFlow: () => void;

  // Consent
  addConsentRequest: (request: ConsentRequest) => void;
  removeConsentRequest: (requestId: string) => void;
  snoozeConsentRequest: (requestId: string) => void;

  // State
  setRefreshing: (isRefreshing: boolean) => void;
  setError: (error: string | null) => void;
  setInitialized: (initialized: boolean) => void;
}

// ---------------------------------------------------------------------------
// Telemetry Events (from AGENT_AUTH_ARCHITECTURE.md §10)
// ---------------------------------------------------------------------------

export type AuthTelemetryEvent =
  | 'auth_login_started'
  | 'auth_login_completed'
  | 'auth_login_failed'
  | 'auth_logout'
  | 'auth_token_refreshed'
  | 'auth_token_refresh_failed'
  | 'auth_consent_prompt_shown'
  | 'auth_consent_approved'
  | 'auth_consent_denied'
  | 'auth_consent_snoozed'
  | 'auth_consent_details_viewed'
  | 'auth_mfa_challenge_shown'
  | 'auth_mfa_challenge_completed';

export interface AuthTelemetryPayload {
  event: AuthTelemetryEvent;
  surface: ActorSurface;
  actorId?: string;
  actorType?: ActorType;
  toolName?: string;
  scopes?: string[];
  mfaRequired?: boolean;
  mfaVerified?: boolean;
  durationMs?: number;
  error?: string;
}

// ---------------------------------------------------------------------------
// Federated Identity Types (Social Login)
// ---------------------------------------------------------------------------

export type OAuthProvider = 'github' | 'google';

export interface FederatedIdentity {
  id: string;
  provider: OAuthProvider;
  providerUserId: string;
  providerEmail?: string;
  providerUsername?: string;
  providerDisplayName?: string;
  providerAvatarUrl?: string;
  createdAt: string;
}

export type LinkingResult =
  | 'linked_new_user'
  | 'linked_existing'
  | 'linked_manual'
  | 'already_linked'
  | 'requires_password'
  | 'requires_mfa'
  | 'email_conflict'
  | 'invalid_password'
  | 'error';

export interface LinkIdentityRequest {
  provider: OAuthProvider;
  oauthAccessToken: string;
  oauthRefreshToken?: string;
  passwordConfirmation?: string;
  targetUserId?: string;
}

export interface LinkIdentityResponse {
  status: 'success' | 'requires_confirmation' | 'error';
  result: LinkingResult;
  message?: string;
  requiresEmail?: string;
  user?: {
    id: string;
    username: string;
    email?: string;
    emailVerified: boolean;
    displayName?: string;
  };
  identity?: {
    id: string;
    provider: OAuthProvider;
    providerUserId: string;
    providerEmail?: string;
    providerUsername?: string;
  };
}

export interface LinkedProvidersResponse {
  userId: string;
  hasPassword: boolean;
  linkedProviders: FederatedIdentity[];
  providerCount: number;
}

// ---------------------------------------------------------------------------
// MFA Types
// ---------------------------------------------------------------------------

export type MfaDeviceType = 'totp';

export interface MfaDevice {
  id: string;
  deviceType: MfaDeviceType;
  deviceName: string;
  isPrimary: boolean;
  createdAt: string;
  lastUsedAt?: string;
}

export interface MfaSetupResponse {
  setupId: string;
  secret: string;
  provisioningUri: string;
  qrCodeBase64: string;
  backupCodes?: string[];
}

export interface MfaStatusResponse {
  userId: string;
  mfaEnabled: boolean;
  deviceCount: number;
  primaryDevice?: MfaDevice;
}

// ---------------------------------------------------------------------------
// Email Verification Types
// ---------------------------------------------------------------------------

export interface EmailVerificationStatus {
  userId: string;
  email?: string;
  emailVerified: boolean;
  verificationPending: boolean;
}
