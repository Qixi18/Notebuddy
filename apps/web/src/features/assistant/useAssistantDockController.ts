import { useCallback, useEffect, useState } from 'react'

import type { AIAction } from '../notebook-editor/NotebookEditor'
import { readStorage, writeStorage } from '../../utils/safeStorage'
import { DOCK_STORAGE, resolveDockOpen, resolveDockWidth } from './dockLayout'

export function useAssistantDockController() {
  const [open, setOpen] = useState(() => resolveDockOpen(readStorage(DOCK_STORAGE.open)))
  const [width, setWidth] = useState(() => resolveDockWidth(readStorage(DOCK_STORAGE.width)))
  const [resizing, setResizing] = useState(false)
  const [notebookAction, setNotebookAction] = useState<AIAction | null>(null)

  useEffect(() => {
    const openAssistant = (event: Event) => {
      setOpen(true)
      const action = (event as CustomEvent<{ action?: AIAction }>).detail?.action
      setNotebookAction(action ?? null)
    }
    window.addEventListener('notebuddy:open-assistant', openAssistant)
    return () => window.removeEventListener('notebuddy:open-assistant', openAssistant)
  }, [])

  useEffect(() => { writeStorage(DOCK_STORAGE.open, String(open)) }, [open])
  useEffect(() => { writeStorage(DOCK_STORAGE.width, String(width)) }, [width])
  const clearNotebookAction = useCallback(() => setNotebookAction(null), [])

  return {
    open,
    setOpen,
    width,
    setWidth,
    resizing,
    setResizing,
    notebookAction,
    clearNotebookAction,
  }
}
