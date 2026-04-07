/**
 * Onboarding Panel (AMPREALIZE-276 / E2 Phase 3)
 *
 * Webview panel for workspace bootstrap onboarding:
 * - Detects workspace profile via MCP bootstrap.detect
 * - Displays profile with confidence and signal evidence
 * - Lets user confirm or override the detected profile
 * - Runs bootstrap.init to scaffold AGENTS.md and pack
 * - Shows summary of files created and next steps
 */
import * as vscode from 'vscode';
import { McpClient } from '../client/McpClient';
export declare class OnboardingPanel {
    static currentPanel: OnboardingPanel | undefined;
    static readonly viewType = "amprealize.onboarding";
    private readonly _panel;
    private readonly _extensionUri;
    private readonly _mcpClient;
    private _disposables;
    private _step;
    private _detecting;
    private _initializing;
    private _detection;
    private _status;
    private _initResult;
    private _selectedProfile;
    private _error;
    private _workspacePath;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, mcpClient: McpClient): void;
    /**
     * Check if workspace needs onboarding and prompt user
     */
    static checkAndPrompt(extensionUri: vscode.Uri, mcpClient: McpClient): Promise<void>;
    dispose(): void;
    private runDetection;
    private initWorkspace;
    private update;
    private getHtmlForWebview;
    private renderStepIndicator;
    private renderContent;
    private renderStepContent;
    private renderDetectStep;
    private renderConfirmStep;
    private renderInitStep;
    private renderCompleteStep;
    private escapeHtml;
}
//# sourceMappingURL=OnboardingPanel.d.ts.map
