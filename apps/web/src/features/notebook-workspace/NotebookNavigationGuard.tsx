import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

import { shouldBlockNoteNavigation } from '../notebook/navigation'
import { ConfirmDialog } from '../../components/ConfirmDialog'

export function NotebookNavigationGuard({
  dirty,
  onDiscard,
}: {
  dirty: boolean
  onDiscard: () => void
}) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    shouldBlockNoteNavigation(dirty, currentLocation, nextLocation),
  )

  useEffect(() => {
    if (!dirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [dirty])

  if (blocker.state !== 'blocked') return null
  return (
    <ConfirmDialog
      eyebrow="未保存的笔记"
      title="离开正在编辑的笔记？"
      description="正文修改尚未保存。离开此页面会丢弃未保存的内容。"
      confirmLabel="放弃草稿并离开"
      cancelLabel="继续编辑"
      tone="danger"
      onConfirm={() => { onDiscard(); blocker.proceed() }}
      onCancel={() => blocker.reset()}
    />
  )
}
