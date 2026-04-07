/**
 * BehaviorAccuracyPanel
 *
 * Webview panel for behavior accuracy scoring and effectiveness metrics.
 * Allows users to:
 * - View behavior effectiveness metrics (usage count, token savings, accuracy)
 * - Submit manual feedback on behavior accuracy
 * - Configure scoring mode (manual vs LLM-as-judge)
 * - View and manage pending accuracy reviews
 *
 * Following `behavior_curate_behavior_handbook` (Student)
 */
import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
export interface BehaviorEffectiveness {
    behavior_id: string;
    behavior_name: string;
    usage_count: number;
    token_savings_pct: number;
    accuracy_score: number;
    feedback_count: number;
    feedback_source: 'manual' | 'llm' | 'hybrid';
    last_updated: string;
}
export interface AccuracyFeedback {
    behavior_id: string;
    run_id?: string;
    query: string;
    was_helpful: boolean;
    accuracy_rating: 1 | 2 | 3 | 4 | 5;
    comment?: string;
    actor_id: string;
    submitted_at?: string;
}
export interface ScoringConfig {
    mode: 'manual' | 'llm' | 'hybrid';
    llm_model?: string;
    auto_score_threshold?: number;
    require_human_review_below?: number;
}
export declare class BehaviorAccuracyPanel {
    private readonly _client;
    private readonly _extensionUri;
    static currentPanel: BehaviorAccuracyPanel | undefined;
    private readonly _panel;
    private _disposables;
    private _behaviors;
    private _effectiveness;
    private _scoringConfig;
    private _selectedBehaviorId;
    private constructor();
    static createOrShow(client: AmprealizeClient, extensionUri: vscode.Uri): void;
    dispose(): void;
    private _loadData;
    private _submitFeedback;
    private _updateScoringConfig;
    private _exportMetrics;
    private _update;
    private _getHtmlForWebview;
}
//# sourceMappingURL=BehaviorAccuracyPanel.d.ts.map
