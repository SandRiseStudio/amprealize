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
import { McpClient, DeviceInitResult, DevicePollResult, WorkspaceProfile } from '../client/McpClient';

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

export class AuthProvider implements vscode.AuthenticationProvider {
    private _onDidChangeSessions = new vscode.EventEmitter<vscode.AuthenticationProviderAuthenticationSessionsChangeEvent>();
    public readonly onDidChangeSessions = this._onDidChangeSessions.event;

    private _sessions = new Map<string, AuthSession>();
    private _client: AmprealizeClient;
    private _mcpClient: McpClient | null = null;
    private _useMcp: boolean;
    private _context?: vscode.ExtensionContext;

    constructor(client: AmprealizeClient, context?: vscode.ExtensionContext, mcpClient?: McpClient) {
        this._client = client;
        this._context = context;

        // Initialize MCP client if context is provided
        const config = vscode.workspace.getConfiguration('amprealize');
        this._useMcp = config.get('useMcpForAuth', true);

        if (mcpClient && this._useMcp) {
            this._mcpClient = mcpClient;
        } else if (context && this._useMcp) {
            this._mcpClient = new McpClient(context);
        }

        this.loadStoredSessions();
    }

    /**
     * Get authentication sessions
     */
    async getSessions(scopes?: string[]): Promise<vscode.AuthenticationSession[]> {
        const sessions: vscode.AuthenticationSession[] = [];

        for (const [sessionId, session] of this._sessions) {
            // Check if session is still valid
            if (session.expiresAt && session.expiresAt < new Date()) {
                // Try to refresh the token
                const refreshed = await this.refreshSession(session);
                if (!refreshed) {
                    continue; // Skip invalid sessions
                }
            }

            sessions.push({
                id: sessionId,
                accessToken: session.accessToken,
                account: {
                    id: session.actor.id,
                    label: session.actor.role
                },
                scopes: session.scopes
            });
        }

        return sessions;
    }

    /**
     * Create a new authentication session
     */
    async createSession(scopes: string[]): Promise<vscode.AuthenticationSession> {
        try {
            // Start OAuth2 device flow
            const deviceCodeResponse = await this.startDeviceFlow(scopes);

            // Show device flow UI
            const session = await this.showDeviceFlowUI(deviceCodeResponse);

            if (session) {
                const authSession: vscode.AuthenticationSession = {
                    id: session.id,
                    accessToken: session.accessToken,
                    account: {
                        id: session.actor.id,
                        label: session.actor.role
                    },
                    scopes: session.scopes
                };

                // Store session
                this._sessions.set(session.id, session);
                this.storeSessions();

                // Notify about the new session
                this._onDidChangeSessions.fire({
                    added: [authSession],
                    changed: [],
                    removed: []
                });

                return authSession;
            }

            throw new Error('Authentication cancelled');
        } catch (error) {
            console.error('Failed to create session:', error);
            if (error instanceof Error) {
                throw error;
            }
            throw new Error('Authentication failed');
        }
    }

    /**
     * Remove an authentication session
     */
    async removeSession(sessionId: string): Promise<void> {
        const session = this._sessions.get(sessionId);
        if (session) {
            this._sessions.delete(sessionId);
            this.storeSessions();

            this._onDidChangeSessions.fire({
                added: [],
                changed: [],
                removed: [{
                    id: sessionId,
                    accessToken: session.accessToken,
                    account: {
                        id: session.actor.id,
                        label: session.actor.role
                    },
                    scopes: session.scopes
                }]
            });

            // Also revoke the token if possible
            try {
                await this.revokeToken(session.accessToken);
            } catch (error) {
                console.warn('Failed to revoke token:', error);
            }
        }
    }

    /**
     * Start OAuth2 device flow (MCP with CLI fallback)
     */
    private async startDeviceFlow(scopes: string[]): Promise<DeviceInitResult> {
        // Try MCP first for real-time communication
        if (this._mcpClient && this._useMcp) {
            try {
                return await this._mcpClient.deviceInit({ scopes });
            } catch (error) {
                console.warn('MCP device init failed, falling back to CLI:', error);
            }
        }

        // Fallback to CLI
        try {
            const response = await this._client.runCLI(['auth', 'device-flow', '--scopes', scopes.join(',')], { parseJson: false });
            return JSON.parse(response) as DeviceInitResult;
        } catch (error) {
            throw new Error(`Failed to start device flow: ${error}`);
        }
    }

    /**
     * Show device flow authentication UI with MCP polling
     */
    private async showDeviceFlowUI(deviceCodeResponse: DeviceInitResult): Promise<AuthSession | null> {
        return new Promise((resolve, reject) => {
            const extensionUri = this._context?.extensionUri
                ?? vscode.extensions.getExtension('amprealize.amprealize-ide-extension')?.extensionUri;

            const panel = vscode.window.createWebviewPanel(
                'amprealize.deviceFlow',
                'Amprealize Authentication',
                vscode.ViewColumn.One,
                {
                    enableScripts: true,
                    retainContextWhenHidden: true,
                    localResourceRoots: extensionUri ? [vscode.Uri.joinPath(extensionUri, 'src')] : []
                }
            );

            const webview = panel.webview;
            webview.html = this.getDeviceFlowHTML(webview, deviceCodeResponse);

            let pollingActive = true;
            let pollInterval: NodeJS.Timeout | null = null;

            // Start automatic polling if MCP is available
            if (this._mcpClient && this._useMcp) {
                pollInterval = setInterval(async () => {
                    if (!pollingActive) {
                        return;
                    }

                    try {
                        const result = await this._mcpClient!.devicePoll({
                            deviceCode: deviceCodeResponse.device_code
                        });

                        webview.postMessage({ type: 'pollStatus', status: result.status });

                        if (result.status === 'authorized' && result.access_token) {
                            pollingActive = false;
                            if (pollInterval) {
                                clearInterval(pollInterval);
                            }

                            const session = this.createSessionFromPollResult(result);
                            panel.dispose();
                            resolve(session);
                        } else if (result.status === 'denied' || result.status === 'expired') {
                            pollingActive = false;
                            if (pollInterval) {
                                clearInterval(pollInterval);
                            }

                            panel.dispose();
                            reject(new Error(`Authentication ${result.status}: ${result.error_description || result.error || 'Unknown error'}`));
                        }
                    } catch (error) {
                        console.warn('Poll failed:', error);
                        // Continue polling on transient errors
                    }
                }, (deviceCodeResponse.interval || 5) * 1000);
            }

            // Handle messages from webview (for manual verification or CLI fallback)
            webview.onDidReceiveMessage(async (message) => {
                switch (message.type) {
                    case 'verifyCode':
                        pollingActive = false;
                        if (pollInterval) {
                            clearInterval(pollInterval);
                        }

                        try {
                            const session = await this.verifyDeviceCode(deviceCodeResponse.device_code, message.userCode);
                            panel.dispose();
                            resolve(session);
                        } catch (error) {
                            const errorMessage = error instanceof Error ? error.message : 'Authentication failed';
                            webview.postMessage({ type: 'error', message: errorMessage });
                        }
                        break;
                    case 'cancel':
                        pollingActive = false;
                        if (pollInterval) {
                            clearInterval(pollInterval);
                        }
                        panel.dispose();
                        reject(new Error('Authentication cancelled'));
                        break;
                }
            });

            panel.onDidDispose(() => {
                pollingActive = false;
                if (pollInterval) {
                    clearInterval(pollInterval);
                }
                reject(new Error('Authentication cancelled'));
            });
        });
    }

    /**
     * Create session from successful poll result
     */
    private createSessionFromPollResult(result: DevicePollResult): AuthSession {
        const now = new Date();
        const expiresAt = result.expires_in
            ? new Date(now.getTime() + (result.expires_in * 1000))
            : undefined;

        return {
            id: `amprealize-${Date.now()}`,
            accessToken: result.access_token!,
            refreshToken: result.refresh_token,
            expiresAt,
            actor: {
                id: 'user',
                role: 'STUDENT',
                surface: 'VSCODE'
            },
            scopes: result.scopes || []
        };
    }

    /**
     * Verify device code and get tokens
     */
    private async verifyDeviceCode(deviceCode: string, userCode: string): Promise<AuthSession> {
        try {
            const response = await this._client.runCLI(['auth', 'verify-device-code', '--device-code', deviceCode, '--user-code', userCode], { parseJson: true });

            const now = new Date();
            const expiresAt = new Date(now.getTime() + (response.expires_in * 1000));

            const session: AuthSession = {
                id: `amprealize-${Date.now()}`,
                accessToken: response.access_token,
                refreshToken: response.refresh_token,
                expiresAt: expiresAt,
                actor: {
                    id: response.actor?.id || 'user',
                    role: response.actor?.role || 'UNKNOWN',
                    surface: 'VSCODE'
                },
                scopes: response.scope?.split(' ') || []
            };

            return session;
        } catch (error) {
            throw new Error(`Failed to verify device code: ${error}`);
        }
    }

    /**
     * Refresh an existing session
     */
    private async refreshSession(session: AuthSession): Promise<boolean> {
        if (!session.refreshToken) {
            return false;
        }

        try {
            let response: any;

            // Try MCP first
            if (this._mcpClient && this._useMcp) {
                try {
                    response = await this._mcpClient.callTool('auth.refresh', {
                        refresh_token: session.refreshToken
                    });
                } catch (mcpError) {
                    console.warn('MCP refresh failed, falling back to CLI:', mcpError);
                    this._useMcp = false;
                }
            }

            // Fallback to CLI
            if (!response) {
                response = await this._client.runCLI(
                    ['auth', 'refresh-token', '--refresh-token', session.refreshToken],
                    { parseJson: true }
                );
            }

            // Update session with new tokens
            const now = new Date();
            session.accessToken = response.access_token;
            session.refreshToken = response.refresh_token || session.refreshToken;
            session.expiresAt = new Date(now.getTime() + (response.expires_in * 1000));

            // Update in storage
            this._sessions.set(session.id, session);
            this.storeSessions();

            return true;
        } catch (error) {
            console.error('Failed to refresh token:', error);
            // Remove invalid session
            this._sessions.delete(session.id);
            this.storeSessions();
            return false;
        }
    }

    /**
     * Revoke a token
     */
    private async revokeToken(accessToken: string): Promise<void> {
        try {
            // Try MCP first
            if (this._mcpClient && this._useMcp) {
                try {
                    await this._mcpClient.callTool('auth.logout', {
                        access_token: accessToken
                    });
                    return;
                } catch (mcpError) {
                    console.warn('MCP revoke failed, falling back to CLI:', mcpError);
                }
            }

            // Fallback to CLI
            await this._client.runCLI(
                ['auth', 'revoke-token', '--access-token', accessToken],
                { parseJson: false }
            );
        } catch (error) {
            console.warn('Failed to revoke token:', error);
        }
    }

    /**
     * Get device flow HTML
     */
    private getDeviceFlowHTML(webview: vscode.Webview, deviceCodeResponse: any): string {
        const extensionUri = this._context?.extensionUri
            ?? vscode.extensions.getExtension('amprealize.amprealize-ide-extension')?.extensionUri;
        const baseUri = extensionUri ?? webview.options.localResourceRoots?.[0];
        const scriptUri = baseUri
            ? webview.asWebviewUri(vscode.Uri.joinPath(baseUri, 'src', 'webviews', 'deviceFlow.js'))
            : webview.asWebviewUri(vscode.Uri.joinPath(vscode.Uri.file('.'), 'src', 'webviews', 'deviceFlow.js'));
        const styleUri = baseUri
            ? webview.asWebviewUri(vscode.Uri.joinPath(baseUri, 'src', 'styles', 'AuthFlow.css'))
            : webview.asWebviewUri(vscode.Uri.joinPath(vscode.Uri.file('.'), 'src', 'styles', 'AuthFlow.css'));

        return `<!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Amprealize Authentication</title>
            <link href="${styleUri}" rel="stylesheet">
        </head>
        <body>
            <div class="auth-container">
                <div class="auth-header">
                    <h1>🔐 Amprealize Authentication</h1>
                    <p>Authenticate to access Amprealize services</p>
                </div>

                <div class="auth-instructions">
                    <h2>Complete the authentication process:</h2>
                    <ol>
                        <li>Visit: <strong>${deviceCodeResponse.verification_uri}</strong></li>
                        <li>Enter code: <strong>${deviceCodeResponse.user_code}</strong></li>
                        <li>Authorize the application</li>
                        <li>Click "I've completed authentication" below</li>
                    </ol>
                    ${deviceCodeResponse.scopes ? `<p class="scope-hint">Requested scopes: <code>${deviceCodeResponse.scopes.join(', ')}</code></p>` : ''}
                </div>

                <div class="auth-actions">
                    <button id="verifyBtn" onclick="verifyCode()">I've completed authentication</button>
                    <button id="cancelBtn" onclick="cancelAuth()">Cancel</button>
                </div>

                <div class="auth-status" id="authStatus"></div>
            </div>

            <script nonce="${getNonce()}" src="${scriptUri}"></script>
        </body>
        </html>`;
    }

    /**
     * Load stored sessions from VS Code storage
     */
    private loadStoredSessions(): void {
        const globalState = this._context?.globalState;
        if (globalState) {
            const stored = globalState.get('authSessions', '{}');
            try {
                const sessionsData = JSON.parse(stored);
                for (const [sessionId, sessionData] of Object.entries(sessionsData)) {
                    const session = sessionData as AuthSession;
                    if (session.expiresAt) {
                        session.expiresAt = new Date(session.expiresAt);
                    }
                    this._sessions.set(sessionId, session);
                }
            } catch (error) {
                console.error('Failed to load stored sessions:', error);
            }
        }
    }

    /**
     * Store sessions to VS Code storage
     */
    private storeSessions(): void {
        const globalState = this._context?.globalState;
        if (globalState) {
            const sessionsData: Record<string, AuthSession> = {};
            for (const [sessionId, session] of this._sessions) {
                sessionsData[sessionId] = {
                    ...session,
                    expiresAt: session.expiresAt
                };
            }
            globalState.update('authSessions', JSON.stringify(sessionsData));
        }
    }

    /**
     * Get current session status
     */
    getCurrentSession(): AuthSession | null {
        const sessions = Array.from(this._sessions.values());
        return sessions.length > 0 ? sessions[0] : null;
    }

    /**
     * Check if user is authenticated
     */
    isAuthenticated(): boolean {
        const session = this.getCurrentSession();
        return session !== null && (!session.expiresAt || session.expiresAt > new Date());
    }

    /**
     * Suggest auth scopes based on the detected workspace profile.
     * Returns base scopes plus profile-specific additions with rationale.
     */
    static getScopeGuidance(profile?: WorkspaceProfile): { scopes: string[]; rationale: string } {
        const base = ['behaviors:read', 'runs:write', 'projects:read'];

        switch (profile) {
            case 'compliance-sensitive':
                return {
                    scopes: [...base, 'compliance:read', 'compliance:write', 'audit:read'],
                    rationale: 'Compliance-sensitive workspaces need audit and compliance scopes for policy enforcement.'
                };
            case 'team-collab':
                return {
                    scopes: [...base, 'projects:write', 'boards:read', 'boards:write'],
                    rationale: 'Team collaboration requires project write access and board management scopes.'
                };
            case 'amprealize-platform':
                return {
                    scopes: [...base, 'behaviors:write', 'compliance:read', 'projects:write', 'admin:read'],
                    rationale: 'Platform development benefits from behavior write access and admin visibility.'
                };
            default:
                return {
                    scopes: base,
                    rationale: 'Standard scopes for workspace interaction.'
                };
        }
    }

    /**
     * Dispose of resources
     */
    dispose(): void {
        this._onDidChangeSessions.dispose();

        // Disconnect MCP client
        if (this._mcpClient) {
            this._mcpClient.disconnect();
        }
    }
}

function getNonce(): string {
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let text = '';
    for (let i = 0; i < 8; i++) {
        const index = Math.floor(Math.random() * possible.length);
        text += possible.charAt(index);
    }
    return text;
}
