/**
 * @amprealize/whiteboard-sync-core
 *
 * Shared types, persistence utilities, and the default LocalSyncBackend for
 * all whiteboard sync backends.
 */

export type { SyncBackend, RoomSnapshot } from "./types.js";
export { loadSnapshot, saveSnapshot } from "./persistence.js";
export type { PersistenceConfig } from "./persistence.js";
export { LocalSyncBackend } from "./LocalSyncBackend.js";
export type { LocalSyncBackendConfig } from "./LocalSyncBackend.js";
