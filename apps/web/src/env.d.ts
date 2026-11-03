interface ImportMetaEnv {
  readonly DEV: boolean
  readonly VITE_TREE_GROWTH_ENABLED?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
