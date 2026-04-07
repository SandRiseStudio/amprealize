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
export declare class SettingsSyncProvider implements vscode.FileSystemProvider, vscode.Disposable {
    private _onDidChangeFile;
    readonly onDidChangeFile: vscode.Event<vscode.FileChangeEvent[]>;
    private _settingsCache;
    private _context;
    private _syncInProgress;
    constructor(context: vscode.ExtensionContext);
    stat(uri: vscode.Uri): Promise<vscode.FileStat>;
    readFile(uri: vscode.Uri): Promise<Uint8Array>;
    writeFile(uri: vscode.Uri, content: Uint8Array, options: {
        create: boolean;
        overwrite: boolean;
    }): Promise<void>;
    readDirectory(uri: vscode.Uri): Promise<[string, vscode.FileType][]>;
    createDirectory(uri: vscode.Uri): void;
    delete(uri: vscode.Uri, options: {
        recursive: boolean;
    }): void;
    rename(oldUri: vscode.Uri, newUri: vscode.Uri, options: {
        overwrite: boolean;
    }): void;
    watch(uri: vscode.Uri, options: {
        recursive: boolean;
        excludes: string[];
    }): vscode.Disposable;
    getCurrentSettings(): AmprealizeSettings;
    updateSettings(settings: Partial<AmprealizeSettings>): Promise<void>;
    syncSettings(): Promise<void>;
    exportSettings(): Promise<void>;
    importSettings(): Promise<void>;
    private getTeamSettings;
    private mergeSettings;
    private validateSettings;
    getSettingsUri(): vscode.Uri;
    getProfileUri(): vscode.Uri;
    getTeamUri(): vscode.Uri;
    dispose(): void;
}
//# sourceMappingURL=SettingsSyncProvider.d.ts.map
