/**
 * Reflection/Extraction API hooks
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

// Types based on amprealize/reflection_contracts.py
export interface ReflectionQualityScores {
  clarity: number;
  generality: number;
  reusability: number;
  correctness: number;
}

export interface ReflectionExample {
  title: string;
  body: string;
}

export interface ReflectionCandidate {
  slug: string;
  display_name: string;
  instruction: string;
  summary: string | null;
  supporting_steps: string[];
  examples: ReflectionExample[];
  quality_scores: ReflectionQualityScores;
  confidence: number;
  duplicate_behavior_id: string | null;
  duplicate_behavior_name: string | null;
  tags: string[];
}

export interface ReflectRequest {
  trace_text: string;
  trace_format?: 'chain_of_thought' | 'structured_log' | 'markdown';
  run_id?: string;
  max_candidates?: number;
  min_quality_score?: number;
  include_examples?: boolean;
  preferred_tags?: string[];
}

export interface ReflectResponse {
  run_id: string | null;
  trace_step_count: number;
  candidates: ReflectionCandidate[];
  summary: string | null;
  metadata: {
    elapsed_ms: number;
    window_sizes: number[];
    scanned_snippet_count: number;
    total_candidates: number;
    min_quality_score: number;
  } | null;
}

// Candidate approval status
export type CandidateStatus = 'pending' | 'approved' | 'rejected' | 'auto_approved';

export interface CandidateApprovalRequest {
  slug: string;
  status: CandidateStatus;
  reviewer_notes?: string;
}

export interface CandidateApprovalResponse {
  slug: string;
  status: CandidateStatus;
  behavior_id?: string; // Set if approved and behavior was created
}

// Auto-accept threshold (>0.8 confidence)
export const AUTO_ACCEPT_THRESHOLD = 0.8;

// Hooks
export function useReflectionExtract() {
  return useMutation({
    mutationFn: async (request: ReflectRequest): Promise<ReflectResponse> => {
      return apiClient.post('/v1/reflection/extract', request);
    },
  });
}

export function useApproveCandidate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CandidateApprovalRequest): Promise<CandidateApprovalResponse> => {
      return apiClient.post('/v1/reflection/candidates/approve', request);
    },
    onSuccess: () => {
      // Invalidate behavior queries to refresh lists
      queryClient.invalidateQueries({ queryKey: ['behaviors'] });
    },
  });
}

export function useRejectCandidate() {
  return useMutation({
    mutationFn: async (request: { slug: string; reason?: string }): Promise<{ slug: string; status: 'rejected' }> => {
      return apiClient.post('/v1/reflection/candidates/reject', request);
    },
  });
}

// Helper to determine if candidate should be auto-accepted
export function shouldAutoAccept(candidate: ReflectionCandidate): boolean {
  return candidate.confidence >= AUTO_ACCEPT_THRESHOLD && !candidate.duplicate_behavior_id;
}

// Helper to categorize candidates by approval status
export function categorizeCandidates(candidates: ReflectionCandidate[]): {
  autoApproved: ReflectionCandidate[];
  pendingReview: ReflectionCandidate[];
  duplicates: ReflectionCandidate[];
} {
  const autoApproved: ReflectionCandidate[] = [];
  const pendingReview: ReflectionCandidate[] = [];
  const duplicates: ReflectionCandidate[] = [];

  for (const candidate of candidates) {
    if (candidate.duplicate_behavior_id) {
      duplicates.push(candidate);
    } else if (shouldAutoAccept(candidate)) {
      autoApproved.push(candidate);
    } else {
      pendingReview.push(candidate);
    }
  }

  return { autoApproved, pendingReview, duplicates };
}
