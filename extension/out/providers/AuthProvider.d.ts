/**
 * Authentication Provider for Amprealize
 *
 * Handles OAuth2 device flow authentication and token management:
 * - OAuth2 device flow implementation (via MCP or CLI fallback)
 * - Token storage and refresh handling
 * - Session status management
 * - Authentication state notifications
 *
 * Uses MCP client for real-time device flow polling and consent management,
 * with CLI fallback for environments where MCP is unavailable.
 */
import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
import { McpClient, WorkspaceProfile } from '../client/McpClient';
export interface AuthToken {
    access_token: string;
    refresh_token?: string;
    token_type: string;
    expires_in?: number;
    scope?: string;
}
export interface AuthSession {
    id: string;
    accessToken: string;
    refreshToken?: string;
    expiresAt?: Date;
    actor: {
        id: string;
        role: string;
        surface: string;
    };
    scopes: string[];
}
export declare class AuthProvider implements vscode.AuthenticationProvider {
    private _onDidChangeSessions;
    readonly onDidChangeSessions: vscode.Event<vscode.AuthenticationProviderAuthenticationSessionsChangeEvent>;
    private _sessions;
    private _client;
    private _mcpClient;
    private _useMcp;
    private _context?;
    constructor(client: AmprealizeClient, context?: vscode.ExtensionContext, mcpClient?: McpClient);
    /**
     * Get authentication sessions
     */
    getSessions(scopes?: string[]): Promise<vscode.AuthenticationSession[]>;
    /**
     * Create a new authentication session
     */
    createSession(scopes: string[]): Promise<vscode.AuthenticationSession>;
    /**
     * Remove an authentication session
     */
    removeSession(sessionId: string): Promise<void>;
    /**
     * Start OAuth2 device flow (MCP with CLI fallback)
     */
    private startDeviceFlow;
    /**
     * Show device flow authentication UI with MCP polling
     */
    private showDeviceFlowUI;
    /**
     * Create session from successful poll result
     */
    private createSessionFromPollResult;
    /**
     * Verify device code and get tokens
     */
    private verifyDeviceCode;
    /**
     * Refresh an existing session
     */
    private refreshSession;
    /**
     * Revoke a token
     */
    private revokeToken;
    /**
     * Get device flow HTML
     */
    private getDeviceFlowHTML;
    /**
     * Load stored sessions from VS Code storage
     */
    private loadStoredSessions;
    /**
     * Store sessions to VS Code storage
     */
    private storeSessions;
    /**
     * Get current session status
     */
    getCurrentSession(): AuthSession | null;
    /**
     * Check if user is authenticated
     */
    isAuthenticated(): boolean;
    /**
     * Suggest auth scopes based on the detected workspace profile.
     * Returns base scopes plus profile-specific additions with rationale.
     */
    static getScopeGuidance(profile?: WorkspaceProfile): {
        scopes: string[];
        rationale: string;
    };
    /**
     * Dispose of resources
     */
    dispose(): void;
}
//# sourceMappingURL=AuthProvider.d.ts.map
