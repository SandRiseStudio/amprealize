/**
 * API hooks for whiteboard room operations.
 *
 * GUIDEAI-966: Integrate whiteboard canvas into web console
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WhiteboardRoom {
  id: string;
  title: string;
  status: string;
  session_id?: string | null;
  created_by?: string | null;
  participant_ids: string[];
  created_at?: string | null;
  updated_at?: string | null;
  closed_at?: string | null;
}

export interface CreateRoomRequest {
  title: string;
  session_id?: string;
  metadata?: Record<string, unknown>;
}

export interface RoomListResponse {
  rooms: WhiteboardRoom[];
  total: number;
}

export interface CanvasState {
  room_id: string;
  canvas_state: Record<string, unknown>;
  participant_ids: string[];
}

export interface WhiteboardSnapshot {
  id: string;
  room_id: string;
  session_id?: string | null;
  title: string;
  format: string;
  data?: unknown;
  canvas_elements?: Record<string, unknown> | null;
  thumbnail_url?: string | null;
  created_by?: string | null;
  exported_at?: string | null;
  metadata: Record<string, unknown>;
  shared_with: string[];
}

export interface SnapshotListResponse {
  snapshots: WhiteboardSnapshot[];
  total: number;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const whiteboardKeys = {
  all: ['whiteboard'] as const,
  rooms: () => [...whiteboardKeys.all, 'rooms'] as const,
  room: (roomId?: string) => [...whiteboardKeys.all, 'room', roomId] as const,
  canvas: (roomId?: string) => [...whiteboardKeys.all, 'canvas', roomId] as const,
  snapshots: (roomId?: string, sessionId?: string) =>
    [...whiteboardKeys.all, 'snapshots', roomId, sessionId] as const,
};

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

export function useWhiteboardRooms(
  status?: string,
  options?: { refetchInterval?: number },
) {
  return useQuery({
    queryKey: [...whiteboardKeys.rooms(), status],
    queryFn: async (): Promise<WhiteboardRoom[]> => {
      try {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        const qs = params.toString();
        const response = await apiClient.get<RoomListResponse>(
          `/v1/whiteboard/rooms${qs ? `?${qs}` : ''}`,
        );
        return response.rooms ?? [];
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }
    },
    staleTime: 10_000,
    refetchInterval: options?.refetchInterval,
  });
}

export function useWhiteboardRoom(roomId?: string) {
  return useQuery({
    queryKey: whiteboardKeys.room(roomId),
    queryFn: async (): Promise<WhiteboardRoom | null> => {
      if (!roomId) return null;
      try {
        return await apiClient.get<WhiteboardRoom>(`/v1/whiteboard/rooms/${roomId}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(roomId),
    staleTime: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

export function useWhiteboardSnapshots(roomId?: string, sessionId?: string) {
  return useQuery({
    queryKey: whiteboardKeys.snapshots(roomId, sessionId),
    queryFn: async (): Promise<WhiteboardSnapshot[]> => {
      try {
        const params = new URLSearchParams();
        if (roomId) params.set('room_id', roomId);
        if (sessionId) params.set('session_id', sessionId);
        const qs = params.toString();
        const response = await apiClient.get<SnapshotListResponse>(
          `/v1/whiteboard/snapshots${qs ? `?${qs}` : ''}`,
        );
        return response.snapshots ?? [];
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }
    },
    staleTime: 30_000,
  });
}

export function useCreateWhiteboardRoom() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateRoomRequest): Promise<WhiteboardRoom> => {
      return await apiClient.post<WhiteboardRoom>('/v1/whiteboard/rooms', payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: whiteboardKeys.rooms() });
    },
  });
}

export function useJoinWhiteboardRoom() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (roomId: string): Promise<WhiteboardRoom> => {
      return await apiClient.post<WhiteboardRoom>(`/v1/whiteboard/rooms/${roomId}/join`, {});
    },
    onSuccess: (_data, roomId) => {
      queryClient.invalidateQueries({ queryKey: whiteboardKeys.room(roomId) });
    },
  });
}

export function useCloseWhiteboardRoom() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (roomId: string): Promise<{ success: boolean; message: string }> => {
      return await apiClient.post(`/v1/whiteboard/rooms/${roomId}/close`, {});
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: whiteboardKeys.rooms() });
    },
  });
}

export function useSaveCanvas() {
  return useMutation({
    mutationFn: async ({
      roomId,
      canvasState,
    }: {
      roomId: string;
      canvasState: Record<string, unknown>;
    }): Promise<{ success: boolean; message: string }> => {
      return await apiClient.put(`/v1/whiteboard/rooms/${roomId}/canvas`, {
        canvas_state: canvasState,
      });
    },
  });
}
