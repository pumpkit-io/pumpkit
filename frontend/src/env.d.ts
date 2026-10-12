/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BYPASS_AUTH?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
