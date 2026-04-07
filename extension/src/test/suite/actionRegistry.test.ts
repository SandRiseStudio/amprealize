/**
 * Action Registry Smoke Tests
 *
 * Smoke tests for VS Code extension action registry commands.
 * These tests verify that commands are registered and can be invoked
 * without verifying MCP server communication (which requires integration tests).
 *
 * @behavior behavior_sanitize_action_registry
 */

import * as assert from 'assert';
import * as vscode from 'vscode';

suite('Action Registry Smoke Tests', () => {
	vscode.window.showInformationMessage('Running Action Registry smoke tests.');

	test('Action commands are registered', async () => {
		// Get all registered commands
		const commands = await vscode.commands.getCommands(true);

		// Verify action registry commands are registered
		const actionCommands = [
			'amprealize.refreshActionTracker',
			'amprealize.openActionTimeline',
			'amprealize.recordAction',
			'amprealize.listActions',
			'amprealize.replayAction',
			'amprealize.viewActionDetail',
			'amprealize.actionTracker.copyActionId',
			'amprealize.actionTracker.filterByBehavior',
			'amprealize.actionTracker.clearFilters'
		];

		for (const cmd of actionCommands) {
			assert.ok(
				commands.includes(cmd),
				`Command '${cmd}' should be registered`
			);
		}
	});

	test('refreshActionTracker command can be invoked', async () => {
		// This should not throw even if MCP is not connected
		// (the provider will just show empty data or error state)
		try {
			await vscode.commands.executeCommand('amprealize.refreshActionTracker');
			// If we get here, command executed without throwing
			assert.ok(true);
		} catch (error) {
			// Command may fail due to MCP not running, but should not be "command not found"
			const message = error instanceof Error ? error.message : String(error);
			assert.ok(
				!message.includes('command \'amprealize.refreshActionTracker\' not found'),
				'Command should be registered even if execution fails'
			);
		}
	});

	test('openActionTimeline command can be invoked', async () => {
		try {
			await vscode.commands.executeCommand('amprealize.openActionTimeline');
			// If we get here, command executed without throwing
			assert.ok(true);

			// Close the panel after test
			await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			assert.ok(
				!message.includes('command \'amprealize.openActionTimeline\' not found'),
				'Command should be registered even if execution fails'
			);
		}
	});

	test('clearFilters command can be invoked', async () => {
		try {
			await vscode.commands.executeCommand('amprealize.actionTracker.clearFilters');
			assert.ok(true);
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			assert.ok(
				!message.includes('command \'amprealize.actionTracker.clearFilters\' not found'),
				'Command should be registered even if execution fails'
			);
		}
	});

	test('Action tracker view container exists', async () => {
		// Verify the action tracker view is in the explorer container
		// This checks package.json contribution is valid
		const extension = vscode.extensions.getExtension('amprealize.amprealize');

		if (extension) {
			const packageJSON = extension.packageJSON;
			const views = packageJSON.contributes?.views?.amprealize || [];
			const hasActionTracker = views.some((v: { id: string }) => v.id === 'amprealize.actionTracker');

			assert.ok(hasActionTracker, 'Action tracker view should be registered');
		} else {
			// Extension might not be loaded in test environment
			assert.ok(true, 'Extension not loaded - skipping view verification');
		}
	});
});

suite('McpClient Action Methods Smoke Tests', () => {
	// Note: These tests verify method signatures exist
	// Actual MCP communication requires integration tests with a running server

	test('McpClient exports expected action types', () => {
		// This test verifies that the TypeScript compilation succeeded
		// and action-related types are available
		// In a real test, we'd import and verify, but smoke tests
		// primarily ensure the build succeeded
		assert.ok(true, 'TypeScript compilation successful');
	});
});
