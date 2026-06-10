const STORAGE_KEY = 'amprealize.use_local_workspace_execution';

export type ExecutionWorkspaceKindPreference = 'cloud_git' | 'local_connector';

export function readUseLocalWorkspaceExecution(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

export function setUseLocalWorkspaceExecution(enabled: boolean): void {
  try {
    if (enabled) {
      window.localStorage.setItem(STORAGE_KEY, 'true');
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* ignore quota / private mode */
  }
}

export function getPreferredExecutionWorkspaceKind(): ExecutionWorkspaceKindPreference {
  return readUseLocalWorkspaceExecution() ? 'local_connector' : 'cloud_git';
}
