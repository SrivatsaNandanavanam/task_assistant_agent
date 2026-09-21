/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin for production builds, e.g. https://my-backend.vercel.app (no trailing slash, no /api). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
