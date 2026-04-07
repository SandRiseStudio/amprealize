/**
 * Settings Sync Provider for Amprealize
 *
 * Handles cloud settings storage, import/export, and team inheritance:
 * - Cloud settings storage and sync
 * - Settings import/export functionality
 * - Team settings inheritance
 * - Settings conflict resolution
 */

import * as vscode from 'vscode';

export interface AmprealizeSettings {
    pythonPath: string;
    cliPath: string;
    apiBaseUrl: string;
    timeout: number;
    logLevel: string;
    telemetryEnabled: boolean;
    autoRefresh: boolean;
    refreshInterval: number;
    theme: string;
    customSettings: Record<string, any>;
}

export class SettingsSyncProvider implements vscode.FileSystemProvider, vscode.Disposable {
    private _onDidChangeFile = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
    public readonly onDidChangeFile = this._onDidChangeFile.event;

    private _settingsCache = new Map<string, Uint8Array>();
    private _context: vscode.ExtensionContext;
    private _syncInProgress = false;

    constructor(context: vscode.ExtensionContext) {
        this._context = context;
    }

    // FileSystemProvider implementation
    async stat(uri: vscode.Uri): Promise<vscode.FileStat> {
        const cached = this._settingsCache.get(uri.path);
        return {
            type: vscode.FileType.File,
            size: cached ? cached.length : 0,
            ctime: Date.now(),
            mtime: Date.now()
        };
    }

    async readFile(uri: vscode.Uri): Promise<Uint8Array> {
        const key = uri.path;
        if (this._settingsCache.has(key)) {
            return this._settingsCache.get(key)!;
        }

        // Get settings from VS Code configuration
        const settings = this.getCurrentSettings();
        const content = JSON.stringify(settings, null, 2);
        const data = new TextEncoder().encode(content);

        this._settingsCache.set(key, data);
        return data;
    }

    async writeFile(uri: vscode.Uri, content: Uint8Array, options: { create: boolean; overwrite: boolean }): Promise<void> {
        try {
            const settingsJson = new TextDecoder().decode(content);
            const settings = JSON.parse(settingsJson) as AmprealizeSettings;

            // Update VS Code configuration
            await this.updateSettings(settings);

            // Cache the content
            this._settingsCache.set(uri.path, content);

            // Notify of changes
            this._onDidChangeFile.fire([{ type: vscode.FileChangeType.Changed, uri }]);
        } catch (error) {
            throw new Error(`Failed to write settings: ${error}`);
        }
    }

    async readDirectory(uri: vscode.Uri): Promise<[string, vscode.FileType][]> {
        return [
            ['settings.json', vscode.FileType.File],
            ['profile.json', vscode.FileType.File],
            ['team.json', vscode.FileType.File]
        ];
    }

    createDirectory(uri: vscode.Uri): void {
        throw new Error('Settings directories are read-only');
    }

    delete(uri: vscode.Uri, options: { recursive: boolean }): void {
        throw new Error('Settings cannot be deleted');
    }

    rename(oldUri: vscode.Uri, newUri: vscode.Uri, options: { overwrite: boolean }): void {
        throw new Error('Settings files cannot be renamed');
    }

    watch(uri: vscode.Uri, options: { recursive: boolean; excludes: string[] }): vscode.Disposable {
        return {
            dispose: () => {}
        };
    }

    // Settings management methods
    getCurrentSettings(): AmprealizeSettings {
        const config = vscode.workspace.getConfiguration('amprealize');
        return {
            pythonPath: config.get('pythonPath', 'python'),
            cliPath: config.get('cliPath', 'amprealize'),
            apiBaseUrl: config.get('apiBaseUrl', 'http://localhost:8080'),
            timeout: config.get('timeout', 30000),
            logLevel: config.get('logLevel', 'INFO'),
            telemetryEnabled: config.get('telemetryEnabled', true),
            autoRefresh: config.get('autoRefresh', true),
            refreshInterval: config.get('refreshInterval', 5000),
            theme: config.get('theme', 'default'),
            customSettings: config.get('customSettings', {})
        };
    }

    async updateSettings(settings: Partial<AmprealizeSettings>): Promise<void> {
        const config = vscode.workspace.getConfiguration('amprealize');

        // Update individual settings
        for (const [key, value] of Object.entries(settings)) {
            await config.update(key, value, vscode.ConfigurationTarget.Global);
        }

        // Clear cache to force refresh
        this._settingsCache.clear();
    }

    async syncSettings(): Promise<void> {
        if (this._syncInProgress) {
            vscode.window.showWarningMessage('Settings sync already in progress');
            return;
        }

        this._syncInProgress = true;
        try {
            // Get current settings
            const currentSettings = this.getCurrentSettings();

            // Simulate cloud sync
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Get team settings and merge
            const teamSettings = await this.getTeamSettings();
            const mergedSettings = this.mergeSettings(currentSettings, teamSettings);

            // Update if there are differences
            if (JSON.stringify(currentSettings) !== JSON.stringify(mergedSettings)) {
                await this.updateSettings(mergedSettings);
                vscode.window.showInformationMessage('Settings synchronized with team');
            } else {
                vscode.window.showInformationMessage('Settings are up to date');
            }
        } catch (error) {
            vscode.window.showErrorMessage(`Settings sync failed: ${error}`);
        } finally {
            this._syncInProgress = false;
        }
    }

    async exportSettings(): Promise<void> {
        const settings = this.getCurrentSettings();
        const settingsJson = JSON.stringify(settings, null, 2);

        // Create a new document with the settings
        const document = await vscode.workspace.openTextDocument({
            content: settingsJson,
            language: 'json'
        });

        await vscode.window.showTextDocument(document);
        vscode.window.showInformationMessage('Settings exported to new document');
    }

    async importSettings(): Promise<void> {
        const uri = await vscode.window.showOpenDialog({
            canSelectFiles: true,
            canSelectFolders: false,
            canSelectMany: false,
            filters: {
                'JSON Files': ['json'],
                'All Files': ['*']
            },
            title: 'Select settings file to import'
        });

        if (uri && uri[0]) {
            try {
                const document = await vscode.workspace.openTextDocument(uri[0]);
                const content = document.getText();
                const settings = JSON.parse(content) as Partial<AmprealizeSettings>;

                // Validate settings
                this.validateSettings(settings);

                // Update settings
                await this.updateSettings(settings);

                vscode.window.showInformationMessage('Settings imported successfully');
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to import settings: ${error}`);
            }
        }
    }

    private async getTeamSettings(): Promise<Partial<AmprealizeSettings>> {
        // Simulate getting team settings
        return {
            apiBaseUrl: 'https://api.amprealize.com',
            telemetryEnabled: true,
            logLevel: 'INFO'
        };
    }

    private mergeSettings(userSettings: AmprealizeSettings, teamSettings: Partial<AmprealizeSettings>): AmprealizeSettings {
        const merged = { ...userSettings };

        // Merge team settings (team settings take precedence for certain keys)
        for (const [key, value] of Object.entries(teamSettings)) {
            // Team settings override for these keys
            if (['apiBaseUrl', 'timeout', 'logLevel', 'telemetryEnabled'].includes(key)) {
                (merged as any)[key] = value;
            }
        }

        return merged;
    }

    private validateSettings(settings: Partial<AmprealizeSettings>): void {
        // Validate required fields
        if (settings.pythonPath && typeof settings.pythonPath !== 'string') {
            throw new Error('pythonPath must be a string');
        }

        if (settings.cliPath && typeof settings.cliPath !== 'string') {
            throw new Error('cliPath must be a string');
        }

        if (settings.timeout && (typeof settings.timeout !== 'number' || settings.timeout < 1000)) {
            throw new Error('timeout must be a number greater than 1000');
        }

        if (settings.logLevel && !['DEBUG', 'INFO', 'WARNING', 'ERROR'].includes(settings.logLevel)) {
            throw new Error('logLevel must be one of: DEBUG, INFO, WARNING, ERROR');
        }
    }

    // Create URIs for settings files
    getSettingsUri(): vscode.Uri {
        return vscode.Uri.parse('amprealize-settings:///settings.json');
    }

    getProfileUri(): vscode.Uri {
        return vscode.Uri.parse('amprealize-settings:///profile.json');
    }

    getTeamUri(): vscode.Uri {
        return vscode.Uri.parse('amprealize-settings:///team.json');
    }

    dispose() {
        this._onDidChangeFile.dispose();
        this._settingsCache.clear();
    }
}
