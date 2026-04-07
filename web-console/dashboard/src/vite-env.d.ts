/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override embedded dashboard “View source” URL (default: SandRiseStudio/amprealize OSS). */
  readonly VITE_DASHBOARD_SOURCE_REPO_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
