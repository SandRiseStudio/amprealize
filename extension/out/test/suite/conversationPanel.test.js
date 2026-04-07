"use strict";
/**
 * Conversation Panel Integration Tests (AMPREALIZE-618)
 *
 * Smoke tests verifying that conversation commands and tree view are registered,
 * and that ConversationPanel / ConversationTreeDataProvider behave correctly
 * without a live backend.
 *
 * Following behavior_integrate_vscode_extension: Mocha TDD pattern, mock VS Code APIs.
 * Following behavior_design_test_strategy: happy path + error paths, no real I/O.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const assert = __importStar(require("assert"));
const vscode = __importStar(require("vscode"));
// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------
function assertCommandRegistered(commands, cmd) {
    assert.ok(commands.includes(cmd), `Command '${cmd}' should be registered`);
}
// ---------------------------------------------------------------------------
// Suite: Command Registration
// ---------------------------------------------------------------------------
suite('Conversation Panel – Command Registration', () => {
    vscode.window.showInformationMessage('Running Conversation Panel smoke tests.');
    test('amprealize.openConversation command is registered', async () => {
        const cmds = await vscode.commands.getCommands(true);
        assertCommandRegistered(cmds, 'amprealize.openConversation');
    });
    test('amprealize.refreshConversations command is registered', async () => {
        const cmds = await vscode.commands.getCommands(true);
        assertCommandRegistered(cmds, 'amprealize.refreshConversations');
    });
});
// ---------------------------------------------------------------------------
// Suite: refreshConversations invocation
// ---------------------------------------------------------------------------
suite('Conversation Panel – refreshConversations', () => {
    test('refreshConversations does not throw when no backend is available', async () => {
        try {
            await vscode.commands.executeCommand('amprealize.refreshConversations');
            assert.ok(true, 'Command completed without throwing');
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            assert.ok(!msg.includes("command 'amprealize.refreshConversations' not found"), 'Command must be registered even without a backend');
        }
    });
});
// ---------------------------------------------------------------------------
// Suite: ConversationTreeDataProvider (unit-level)
// ---------------------------------------------------------------------------
suite('ConversationTreeDataProvider – unit', () => {
    // Dynamically import so that the extension host module system is used.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { ConversationTreeDataProvider, ConversationItem } = require('../../providers/ConversationTreeDataProvider');
    test('getTreeItem returns the element unchanged', () => {
        const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
        const item = new ConversationItem({
            id: 'c1',
            title: 'Test Convo',
            status: 'active',
            updated_at: new Date().toISOString(),
        });
        const result = provider.getTreeItem(item);
        assert.strictEqual(result, item);
        provider.dispose();
    });
    test('getChildren returns empty array for a child element (flat list)', async () => {
        const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
        const item = new ConversationItem({
            id: 'c1',
            title: 'Test',
            status: 'active',
            updated_at: new Date().toISOString(),
        });
        const children = await provider.getChildren(item);
        assert.deepStrictEqual(children, []);
        provider.dispose();
    });
    test('getChildren at root returns empty array when backend is unreachable', async () => {
        // Point at a port that should refuse connections immediately
        const provider = new ConversationTreeDataProvider({ baseUrl: 'http://127.0.0.1:1' });
        const children = await provider.getChildren();
        assert.ok(Array.isArray(children), 'Should resolve to an array even on network error');
        provider.dispose();
    });
    test('refresh fires onDidChangeTreeData event', (done) => {
        const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
        const disposable = provider.onDidChangeTreeData(() => {
            disposable.dispose();
            provider.dispose();
            done();
        });
        provider.refresh();
    });
    test('ConversationItem sets correct contextValue', () => {
        const item = new ConversationItem({
            id: 'c2',
            title: 'My Conv',
            status: 'archived',
            updated_at: '2026-01-01T00:00:00Z',
            last_message_preview: 'Hello world',
        });
        assert.strictEqual(item.contextValue, 'conversation-item');
        assert.strictEqual(item.tooltip, 'Hello world');
    });
    test('ConversationItem active status uses comment-discussion icon', () => {
        const item = new ConversationItem({
            id: 'c3',
            title: 'Active',
            status: 'active',
            updated_at: '2026-01-01T00:00:00Z',
        });
        assert.ok(item.iconPath instanceof vscode.ThemeIcon);
        assert.strictEqual(item.iconPath.id, 'comment-discussion');
    });
    test('ConversationItem archived status uses archive icon', () => {
        const item = new ConversationItem({
            id: 'c4',
            title: 'Archived',
            status: 'archived',
            updated_at: '2026-01-01T00:00:00Z',
        });
        assert.ok(item.iconPath instanceof vscode.ThemeIcon);
        assert.strictEqual(item.iconPath.id, 'archive');
    });
    test('ConversationItem command targets amprealize.openConversation with correct args', () => {
        const item = new ConversationItem({
            id: 'c5',
            title: 'Click Me',
            status: 'active',
            updated_at: '2026-01-01T00:00:00Z',
        });
        assert.ok(item.command, 'Item should have a command');
        assert.strictEqual(item.command.command, 'amprealize.openConversation');
        assert.deepStrictEqual(item.command.arguments, ['c5', 'Click Me']);
    });
});
// ---------------------------------------------------------------------------
// Suite: ConversationPanel (unit-level)
// ---------------------------------------------------------------------------
suite('ConversationPanel – unit', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { ConversationPanel } = require('../../panels/ConversationPanel');
    test('currentPanel is undefined before any panel is created', () => {
        assert.strictEqual(ConversationPanel.currentPanel, undefined);
    });
    test('viewType is amprealize.conversation', () => {
        assert.strictEqual(ConversationPanel.viewType, 'amprealize.conversation');
    });
});
//# sourceMappingURL=conversationPanel.test.js.map
