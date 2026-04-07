/**
 * BCI (Behavior-Conditioned Inference) API hooks
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { apiClient } from './client';

// Types based on amprealize/bci_contracts.py
export interface BehaviorMatch {
  behavior_id: string;
  name: string;
  instruction: string;
  score: number;
  relevance_explanation?: string;
  tags: string[];
}

export interface RetrieveRequest {
  query: string;
  top_k?: number;
  filters?: {
    tags?: string[];
    min_score?: number;
    status?: string;
  };
}

export interface RetrieveResponse {
  matches: BehaviorMatch[];
  query: string;
  total_behaviors_searched: number;
  retrieval_time_ms: number;
}

export interface ValidateCitationsRequest {
  text: string;
  expected_behaviors?: string[];
}

export interface CitationValidation {
  behavior_id: string;
  cited: boolean;
  valid: boolean;
  suggestion?: string;
}

export interface ValidateCitationsResponse {
  citations: CitationValidation[];
  missing_citations: string[];
  invalid_citations: string[];
  compliance_rate: number;
}

export interface ParsedCitation {
  behavior_id: string;
  start_index: number;
  end_index: number;
}

export interface ParseCitationsResponse {
  citations: ParsedCitation[];
  text: string;
}

export interface TokenSavingsResponse {
  original_tokens: number;
  optimized_tokens: number;
  savings_tokens: number;
  savings_percentage: number;
}

// Hooks
export function useBCIRetrieve() {
  return useMutation({
    mutationFn: async (request: RetrieveRequest): Promise<RetrieveResponse> => {
      return apiClient.post('/v1/bci/retrieve', request);
    },
  });
}

export function useBCIValidateCitations() {
  return useMutation({
    mutationFn: async (request: ValidateCitationsRequest): Promise<ValidateCitationsResponse> => {
      return apiClient.post('/v1/bci/validate-citations', request);
    },
  });
}

export function useBCIParseCitations() {
  return useMutation({
    mutationFn: async (text: string): Promise<ParseCitationsResponse> => {
      return apiClient.post('/v1/bci/parse-citations', { text });
    },
  });
}

export function useBCIStatus() {
  return useQuery({
    queryKey: ['bci', 'status'],
    queryFn: async () => {
      return apiClient.get<{ status: string; behavior_count: number; index_built: boolean }>('/v1/bci/status');
    },
    staleTime: 30000, // 30 seconds
  });
}

export function useComputeTokenSavings() {
  return useMutation({
    mutationFn: async (request: { original_text: string; optimized_text: string }): Promise<TokenSavingsResponse> => {
      return apiClient.post('/v1/bci/compute-token-savings', request);
    },
  });
}
