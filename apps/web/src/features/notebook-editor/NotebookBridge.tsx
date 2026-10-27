import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { SelectionAnchor } from './NotebookEditor'
import type { DocNode } from './document'

export type NotebookBridgeValue = {
  courseId: string
  notebookId: string
  title: string
  revision: number
  editVersion: number
  excerpt: string
  selection: SelectionAnchor | null
  isDirty: () => boolean
  adoptDocument: (content: DocNode, revision: number, updatedAt: string, expectedEditVersion: number) => boolean
  /** Insert AI output after (or replacing) a captured selection. Returns false when the anchor moved. */
  insertAI: (text: string, mode: 'after' | 'replace', anchor: SelectionAnchor | null, expectedRevision?: number, expectedEditVersion?: number) => boolean
}

type BridgeContextValue = {
  value: NotebookBridgeValue | null
  setValue: (value: NotebookBridgeValue | null) => void
}

const NotebookBridgeContext = createContext<BridgeContextValue | null>(null)

export function NotebookBridgeProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<NotebookBridgeValue | null>(null)
  return <NotebookBridgeContext.Provider value={{ value, setValue }}>{children}</NotebookBridgeContext.Provider>
}

export function useNotebookBridge(): NotebookBridgeValue | null {
  return useContext(NotebookBridgeContext)?.value ?? null
}

export function useRegisterNotebookBridge(value: NotebookBridgeValue | null) {
  const context = useContext(NotebookBridgeContext)
  const setValue = context?.setValue
  useEffect(() => {
    if (!setValue) return
    setValue(value)
  }, [setValue, value])
  useEffect(() => () => { setValue?.(null) }, [setValue])
}
