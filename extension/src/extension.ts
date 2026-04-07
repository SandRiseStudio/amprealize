/**
 * Amprealize VS Code Extension
 *
 * Complete IDE Integration including:
 * - Execution Tracker View (Epic 5.4)
 * - Compliance Review Panel (Epic 5.5)
 * - Authentication Flows (Epic 5.6)
 * - Settings Sync (Epic 5.7)
 * - Keyboard Shortcuts (Epic 5.8)
 * - VSIX Packaging (Epic 5.9)
 */

import * as vscode from 'vscode';
import { AmprealizeClient } from './client/AmprealizeClient';
import { McpClient } from './client/McpClient';
import { ExecutionTrackerDataProvider, RunTreeItem, RunStepTreeItem } from './providers/ExecutionTrackerDataProvider';
import { ComplianceTreeDataProvider, ComplianceChecklistItem, ComplianceStepItem, ComplianceCommentItem } from './providers/ComplianceTreeDataProvider';
import { ActionTreeDataProvider, ActionTreeItem } from './providers/ActionTreeDataProvider';
import { CostTreeDataProvider } from './providers/CostTreeDataProvider';
import { AuthProvider } from './providers/AuthProvider';
import { SettingsSyncProvider } from './providers/SettingsSyncProvider';
import { RunDetailPanel } from './panels/RunDetailPanel';
import { ComplianceReviewPanel } from './panels/ComplianceReviewPanel';
import { BreakerAmpPanel } from './panels/BreakerAmpPanel';
import { ActionTimelinePanel } from './panels/ActionTimelinePanel';
import { BehaviorAccuracyPanel } from './panels/BehaviorAccuracyPanel';
import { AmprealizeChatPanel } from './panels/AmprealizeChatPanel';
import { ConversationPanel } from './panels/ConversationPanel';
import { ConversationTreeDataProvider } from './providers/ConversationTreeDataProvider';
import { McpStatusBarProvider } from './providers/McpStatusBarProvider';
import { OnboardingPanel } from './panels/OnboardingPanel';

export function activate(context: vscode.ExtensionContext) {
	console.log('Amprealize extension is now active');

	// Create output channel for extension logging
	const outputChannel = vscode.window.createOutputChannel('Amprealize Extension');
	outputChannel.appendLine('Amprealize extension activating...');

	try {
		// Initialize AmprealizeClient
		const client = new AmprealizeClient(context);

		// Initialize McpClient for MCP-based operations (behavior_prefer_mcp_tools)
		const mcpClient = new McpClient(context);
		context.subscriptions.push({ dispose: () => mcpClient.dispose() });

		// Initialize MCP Status Bar Provider (Epic 6 - Connection Stability)
		const mcpStatusBarProvider = new McpStatusBarProvider(mcpClient);
		context.subscriptions.push(mcpStatusBarProvider);

		// Register core commands early to avoid "command not found" if later init fails
		context.subscriptions.push(
			vscode.commands.registerCommand('amprealize.openChat', () => {
				AmprealizeChatPanel.createOrShow(context.extensionUri, mcpClient);
			}),
			vscode.commands.registerCommand('amprealize.mcp.showStatus', () => {
				mcpStatusBarProvider.showStatusQuickPick();
			})
		);

		// NOTE: Auto-connect disabled to prevent resource exhaustion
		// User must manually connect via command palette: "Amprealize: Connect to MCP Server"
		outputChannel.appendLine('Amprealize extension ready. Use "Amprealize: Connect to MCP Server" to connect.');

		// Register manual connect command
		context.subscriptions.push(
			vscode.commands.registerCommand('amprealize.mcp.connect', async () => {
				try {
					outputChannel.appendLine('Connecting to MCP server...');
					await mcpClient.connect();
					outputChannel.appendLine('MCP client connected successfully');
					vscode.window.showInformationMessage('Amprealize MCP server connected');
				} catch (err) {
					const errorMsg = err instanceof Error ? err.message : String(err);
					outputChannel.appendLine(`Failed to connect MCP client: ${errorMsg}`);
					vscode.window.showErrorMessage(`Amprealize MCP connection failed: ${errorMsg}`);
				}
			}),
			vscode.commands.registerCommand('amprealize.mcp.disconnect', () => {
				try {
					mcpClient.disconnect();
					outputChannel.appendLine('MCP client disconnected');
					vscode.window.showInformationMessage('Amprealize MCP server disconnected');
				} catch (err) {
					const errorMsg = err instanceof Error ? err.message : String(err);
					outputChannel.appendLine(`Failed to disconnect MCP client: ${errorMsg}`);
				}
			})
		);

		// Register tree data providers
		const executionTrackerProvider = new ExecutionTrackerDataProvider(client);
		const complianceTrackerProvider = new ComplianceTreeDataProvider(client);
		const actionTrackerProvider = new ActionTreeDataProvider(mcpClient);
		const costTrackerProvider = new CostTreeDataProvider(client);

		// Register authentication provider (Epic 5.6)
		const authProvider = new AuthProvider(client, context, mcpClient);
	context.subscriptions.push(vscode.authentication.registerAuthenticationProvider('amprealize', 'Amprealize', authProvider));

	// Register settings sync provider (Epic 5.7)
	const settingsSyncProvider = new SettingsSyncProvider(context);
	context.subscriptions.push(vscode.workspace.registerFileSystemProvider('amprealize-settings', settingsSyncProvider, { isCaseSensitive: true }));

	// Initialize conversation tree provider (AMPREALIZE-568, Phase 9)
	const amprealizeConfig = vscode.workspace.getConfiguration('amprealize');
	const conversationBaseUrl: string = amprealizeConfig.get('serverUrl') || 'http://localhost:8080';
	const conversationTreeProvider = new ConversationTreeDataProvider({ baseUrl: conversationBaseUrl });

	// Register tree views
	const executionTrackerView = vscode.window.registerTreeDataProvider('amprealize.executionTracker', executionTrackerProvider);
	const complianceTrackerView = vscode.window.registerTreeDataProvider('amprealize.complianceTracker', complianceTrackerProvider);
	const actionTrackerView = vscode.window.registerTreeDataProvider('amprealize.actionTracker', actionTrackerProvider);
	const costTrackerView = vscode.window.registerTreeDataProvider('amprealize.costTracker', costTrackerProvider);
	const conversationsView = vscode.window.registerTreeDataProvider('amprealize.conversations', conversationTreeProvider);

	// Register commands
	const commands = [
		// Execution Tracker Commands (Epic 5.4)
		vscode.commands.registerCommand('amprealize.refreshExecutionTracker', () => executionTrackerProvider.refresh()),
		vscode.commands.registerCommand('amprealize.viewRunDetails', async (run) => {
			RunDetailPanel.createOrShow(vscode.Uri.joinPath(context.extensionUri, 'src'), run);
		}),

		// BreakerAmp Orchestrator Commands (Epic 9.5)
		vscode.commands.registerCommand('amprealize.openBreakerAmp', () => {
			BreakerAmpPanel.createOrShow(context.extensionUri, client, mcpClient);
		}),

		// Onboarding / Bootstrap Commands (AMPREALIZE-276 E2)
		vscode.commands.registerCommand('amprealize.openOnboarding', () => {
			OnboardingPanel.createOrShow(context.extensionUri, mcpClient);
		}),

		// Compliance Tracker Commands (Epic 5.5)
		vscode.commands.registerCommand('amprealize.refreshComplianceTracker', () => complianceTrackerProvider.refresh()),
		vscode.commands.registerCommand('amprealize.openComplianceReview', async (checklist) => {
			ComplianceReviewPanel.createOrShow(vscode.Uri.joinPath(context.extensionUri, 'src'), client, checklist);
		}),
		vscode.commands.registerCommand('amprealize.createComplianceChecklist', async () => {
			// TODO: Implement create compliance checklist
			vscode.window.showInformationMessage('Create compliance checklist - feature coming soon');
		}),

		// Authentication Commands (Epic 5.6)
		vscode.commands.registerCommand('amprealize.auth.signIn', async () => {
			const session = await vscode.authentication.getSession('amprealize', ['read', 'write'], { createIfNone: true });
			if (session) {
				vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
			}
		}),
		vscode.commands.registerCommand('amprealize.auth.signOut', async () => {
			// Note: Logout functionality depends on VS Code version
			vscode.window.showInformationMessage('Please use Settings > Accounts to sign out');
		}),
		vscode.commands.registerCommand('amprealize.auth.status', async () => {
			const session = await vscode.authentication.getSession('amprealize', ['read', 'write'], { createIfNone: false });
			if (session) {
				vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
			} else {
				vscode.window.showInformationMessage('Not signed in');
			}
		}),

		// Settings Sync Commands (Epic 5.7)
		vscode.commands.registerCommand('amprealize.settings.sync', async () => {
			await settingsSyncProvider.syncSettings();
			vscode.window.showInformationMessage('Settings synchronized');
		}),
		vscode.commands.registerCommand('amprealize.settings.export', async () => {
			await settingsSyncProvider.exportSettings();
		}),
		vscode.commands.registerCommand('amprealize.settings.import', async () => {
			await settingsSyncProvider.importSettings();
		}),

		// Keyboard Shortcuts (Epic 5.8)
		vscode.commands.registerCommand('amprealize.quickActions', async () => {
			const quickActions = [
				'Refresh Execution Tracker',
				'View Run Details',
				'Open Compliance Review',
				'Sync Settings',
				'Sign In'
			];
			const selected = await vscode.window.showQuickPick(quickActions, {
				placeHolder: 'Select a Amprealize action'
			});

			if (selected) {
				switch (selected) {
					case 'Refresh Execution Tracker':
						await executionTrackerProvider.refresh();
						break;
					case 'Sync Settings':
						await settingsSyncProvider.syncSettings();
						break;
					case 'Sign In': {
						const session = await vscode.authentication.getSession('amprealize', ['read', 'write'], { createIfNone: true });
						if (session) {
							vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
						}
						break;
					}
				}
			}
		}),

		// General commands
		vscode.commands.registerCommand('amprealize.showOutput', () => {
			client.dispose();
		}),

		// Context menu commands for tree view items
		vscode.commands.registerCommand('amprealize.executionTracker.copyRunId', async (item: RunTreeItem) => {
			await vscode.env.clipboard.writeText(item.run.run_id);
			vscode.window.showInformationMessage('Run ID copied to clipboard');
		}),

		vscode.commands.registerCommand('amprealize.executionTracker.refreshRun', async (item: RunTreeItem) => {
			await executionTrackerProvider.refresh();
		}),

		vscode.commands.registerCommand('amprealize.complianceTracker.createChecklist', async () => {
			// TODO: Implement create checklist functionality
			vscode.window.showInformationMessage('Create checklist - feature coming soon');
		}),

		vscode.commands.registerCommand('amprealize.complianceTracker.refreshChecklist', async (item: ComplianceChecklistItem) => {
			await complianceTrackerProvider.refresh();
		}),

		// Action Registry Commands (behavior_sanitize_action_registry)
		vscode.commands.registerCommand('amprealize.refreshActionTracker', () => {
			actionTrackerProvider.refresh();
		}),

		vscode.commands.registerCommand('amprealize.openActionTimeline', () => {
			ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
		}),

		vscode.commands.registerCommand('amprealize.recordAction', async () => {
			// Quick action recording dialog
			const artifactPath = await vscode.window.showInputBox({
				prompt: 'Artifact path (file, directory, or URL)',
				placeHolder: 'e.g., src/services/ActionService.ts'
			});
			if (!artifactPath) {
				return;
			}

			const summary = await vscode.window.showInputBox({
				prompt: 'Action summary (max 160 chars)',
				placeHolder: 'e.g., Added action replay functionality'
			});
			if (!summary) {
				return;
			}

			const behaviorsInput = await vscode.window.showInputBox({
				prompt: 'Behaviors cited (comma-separated)',
				placeHolder: 'e.g., behavior_sanitize_action_registry, behavior_prefer_mcp_tools'
			});
			const behaviorsCited = behaviorsInput
				? behaviorsInput.split(',').map(b => b.trim()).filter(Boolean)
				: [];

			try {
				const result = await mcpClient.actionCreate({
					artifactPath,
					summary,
					behaviorsCited
				});
				vscode.window.showInformationMessage(`Action recorded: ${result.action_id}`);
				actionTrackerProvider.refresh();
			} catch (error) {
				const errorMsg = error instanceof Error ? error.message : String(error);
				vscode.window.showErrorMessage(`Failed to record action: ${errorMsg}`);
			}
		}),

		vscode.commands.registerCommand('amprealize.listActions', async () => {
			try {
				const result = await mcpClient.actionList({ limit: 20 });

				if (result.actions.length === 0) {
					vscode.window.showInformationMessage('No actions recorded yet');
					return;
				}

				const items = result.actions.map(action => ({
					label: action.summary,
					description: action.artifact_path,
					detail: `${action.timestamp} • ${action.behaviors_cited?.join(', ') || 'No behaviors'}`,
					action
				}));

				const selected = await vscode.window.showQuickPick(items, {
					placeHolder: 'Select an action to view details'
				});

				if (selected) {
					ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
				}
			} catch (error) {
				const errorMsg = error instanceof Error ? error.message : String(error);
				vscode.window.showErrorMessage(`Failed to list actions: ${errorMsg}`);
			}
		}),

		vscode.commands.registerCommand('amprealize.replayAction', async (item?: ActionTreeItem) => {
			let actionId: string | undefined;

			if (item?.action) {
				actionId = item.action.action_id;
			} else {
				// Show quick pick to select action
				try {
					const result = await mcpClient.actionList({ limit: 50 });
					if (result.actions.length === 0) {
						vscode.window.showInformationMessage('No actions available to replay');
						return;
					}

					const items = result.actions.map(action => ({
						label: action.summary,
						description: action.artifact_path,
						detail: `Status: ${action.replay_status || 'NOT_STARTED'}`,
						actionId: action.action_id
					}));

					const selected = await vscode.window.showQuickPick(items, {
						placeHolder: 'Select an action to replay'
					});

					if (!selected) {
						return;
					}
					actionId = selected.actionId;
				} catch (error) {
					const errorMsg = error instanceof Error ? error.message : String(error);
					vscode.window.showErrorMessage(`Failed to load actions: ${errorMsg}`);
					return;
				}
			}

			if (!actionId) {
				return;
			}

			// Ask about dry run
			const dryRun = await vscode.window.showQuickPick(
				[
					{ label: '▶ Execute Replay', description: 'Run the replay and apply changes', dryRun: false },
					{ label: '🔍 Dry Run', description: 'Simulate replay without making changes', dryRun: true }
				],
				{ placeHolder: 'Select replay mode' }
			);

			if (!dryRun) {
				return;
			}

			try {
				const result = await mcpClient.actionReplay({
					actionIds: [actionId],
					strategy: 'SEQUENTIAL',
					options: { dryRun: dryRun.dryRun }
				});

				vscode.window.showInformationMessage(
					dryRun.dryRun
						? `Dry run started: ${result.replay_id}`
						: `Replay started: ${result.replay_id}`
				);

				// Refresh action tracker to show updated status
				actionTrackerProvider.refresh();
			} catch (error) {
				const errorMsg = error instanceof Error ? error.message : String(error);
				vscode.window.showErrorMessage(`Failed to start replay: ${errorMsg}`);
			}
		}),

		vscode.commands.registerCommand('amprealize.viewActionDetail', async (item: ActionTreeItem) => {
			if (!item?.action) {
				return;
			}
			// Open action timeline and select this action
			ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
		}),

		vscode.commands.registerCommand('amprealize.actionTracker.copyActionId', async (item: ActionTreeItem) => {
			if (item?.action?.action_id) {
				await vscode.env.clipboard.writeText(item.action.action_id);
				vscode.window.showInformationMessage('Action ID copied to clipboard');
			}
		}),

		vscode.commands.registerCommand('amprealize.actionTracker.filterByBehavior', async () => {
			const behaviorId = await vscode.window.showInputBox({
				prompt: 'Filter by behavior ID',
				placeHolder: 'e.g., behavior_sanitize_action_registry'
			});
			if (behaviorId) {
				actionTrackerProvider.filterByBehavior(behaviorId);
			}
		}),

		vscode.commands.registerCommand('amprealize.actionTracker.clearFilters', () => {
			actionTrackerProvider.clearFilters();
		}),

		// Cost Analytics Commands
		vscode.commands.registerCommand('amprealize.refreshCostTracker', () => {
			costTrackerProvider.refresh();
		}),

		vscode.commands.registerCommand('amprealize.costTracker.setPeriod7d', () => {
			costTrackerProvider.setPeriod(7);
			vscode.window.showInformationMessage('Cost analytics: showing last 7 days');
		}),

		vscode.commands.registerCommand('amprealize.costTracker.setPeriod30d', () => {
			costTrackerProvider.setPeriod(30);
			vscode.window.showInformationMessage('Cost analytics: showing last 30 days');
		}),

		vscode.commands.registerCommand('amprealize.costTracker.setPeriod90d', () => {
			costTrackerProvider.setPeriod(90);
			vscode.window.showInformationMessage('Cost analytics: showing last 90 days');
		}),

		// Behavior Accuracy Commands (behavior_curate_behavior_handbook)
		vscode.commands.registerCommand('amprealize.openBehaviorAccuracy', () => {
			BehaviorAccuracyPanel.createOrShow(client, context.extensionUri);
		}),

		// Conversation Commands (AMPREALIZE-568, Phase 9 - behavior_integrate_vscode_extension)
		vscode.commands.registerCommand('amprealize.openConversation', async (conversationId?: string, conversationTitle?: string) => {
			const session = await vscode.authentication.getSession('amprealize', ['read', 'write'], { createIfNone: false });
			const authToken = session?.accessToken;
			const userId = session?.account.id || 'anonymous';
			const config = { baseUrl: conversationBaseUrl, userId, authToken };

			if (conversationId) {
				ConversationPanel.createOrShow(context.extensionUri, conversationId, conversationTitle || 'Conversation', config);
			} else {
				// Prompt user to pick or create a conversation
				const id = await vscode.window.showInputBox({
					prompt: 'Enter Conversation ID (or leave blank to open last active)',
					placeHolder: 'e.g. conv_abc123'
				});
				if (id !== undefined) {
					ConversationPanel.createOrShow(context.extensionUri, id || 'default', conversationTitle || 'Conversation', config);
				}
			}
		}),

		vscode.commands.registerCommand('amprealize.refreshConversations', () => {
			conversationTreeProvider.refresh();
		}),

		vscode.commands.registerCommand('amprealize.submitBehaviorFeedback', async () => {
			// Quick feedback submission
			const behaviorId = await vscode.window.showInputBox({
				prompt: 'Behavior ID',
				placeHolder: 'e.g., behavior_prefer_mcp_tools'
			});
			if (!behaviorId) { return; }

			const helpful = await vscode.window.showQuickPick(
				[
					{ label: '👍 Yes, helpful', value: true },
					{ label: '👎 No, not helpful', value: false }
				],
				{ placeHolder: 'Was this behavior helpful?' }
			);
			if (!helpful) { return; }

			const rating = await vscode.window.showQuickPick(
				['1', '2', '3', '4', '5'],
				{ placeHolder: 'Accuracy rating (1-5)' }
			);
			if (!rating) { return; }

			try {
				await client.runCLI([
					'behaviors', 'submit-feedback',
					'--behavior-id', behaviorId,
					'--helpful', helpful.value ? 'true' : 'false',
					'--rating', rating
				]);
				vscode.window.showInformationMessage('Feedback submitted successfully');
			} catch (error) {
				vscode.window.showErrorMessage(`Failed to submit feedback: ${error}`);
			}
		})
	];

	// Add all commands to subscriptions
	context.subscriptions.push(
		client,
		authProvider,
		settingsSyncProvider,
		executionTrackerProvider,
		complianceTrackerProvider,
		actionTrackerProvider,
		costTrackerProvider,
		conversationTreeProvider,
		executionTrackerView,
		complianceTrackerView,
		actionTrackerView,
		costTrackerView,
		conversationsView,
		mcpStatusBarProvider,
		...commands
	);
	} catch (error) {
		const errorMsg = error instanceof Error ? error.message : String(error);
		outputChannel.appendLine(`Activation error: ${errorMsg}`);
		console.error('Amprealize extension activation failed:', error);
		vscode.window.showErrorMessage(`Amprealize extension activation failed: ${errorMsg}`);
	}

	// Show welcome message
	vscode.window.showInformationMessage('Amprealize IDE Integration complete! All features available: Execution Tracker, Compliance Review, Auth, Settings Sync.');
}

// This method is called when your extension is deactivated
export function deactivate() {
	console.log('Amprealize extension is now deactivated');
}
