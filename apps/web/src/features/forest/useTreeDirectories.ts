import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { CourseTree } from '../../types'

export function useTreeDirectories() {
  const [trees, setTrees] = useState<Record<string, CourseTree>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const requested = useRef(new Set<string>())
  const inFlight = useRef(new Map<string, Promise<void>>())
  const watched = useRef<string[]>([])
  const [watchKey, setWatchKey] = useState('')
  const [settledVersion, setSettledVersion] = useState(0)
  const snapshots = useRef<Record<string, CourseTree>>({})
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const fetchDirectory = useCallback((id: string) => {
    const existing = inFlight.current.get(id)
    if (existing) return existing
    requested.current.add(id)
    const pending = api.getCourseTree(id).then(tree => {
      if (!mounted.current) return
      const previous = snapshots.current[id]
      const pendingBefore = previous?.notebooks.some(book => book.chapters.some(chapter => ['pending', 'processing'].includes(chapter.status)))
      const pendingAfter = tree.notebooks.some(book => book.chapters.some(chapter => ['pending', 'processing'].includes(chapter.status)))
      snapshots.current[id] = tree
      if (pendingBefore && !pendingAfter) setSettledVersion(value => value + 1)
      setTrees(current => ({ ...current, [id]: tree }))
      setErrors(current => { const next = { ...current }; delete next[id]; return next })
    }).catch((cause: unknown) => {
      requested.current.delete(id)
      if (mounted.current) setErrors(current => ({ ...current, [id]: cause instanceof Error ? cause.message : '目录读取失败' }))
    }).finally(() => { inFlight.current.delete(id) })
    inFlight.current.set(id, pending)
    return pending
  }, [])
  const load = useCallback((ids: string[]) => {
    for (const id of ids) if (!requested.current.has(id)) void fetchDirectory(id)
  }, [fetchDirectory])
  const refresh = useCallback((ids?: string[]) => Promise.all((ids ?? watched.current).map(fetchDirectory)), [fetchDirectory])
  const watch = useCallback((ids: string[]) => {
    watched.current = [...new Set(ids)]
    setWatchKey([...watched.current].sort().join('|'))
    load(ids)
  }, [load])
  const pendingKey = watchKey.split('|').filter(id => trees[id]?.notebooks.some(book => book.chapters.some(chapter => chapter.status === 'pending' || chapter.status === 'processing'))).join('|')
  useEffect(() => {
    if (!pendingKey) return
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void refresh(pendingKey.split('|'))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [pendingKey, refresh])
  return { trees: Object.values(trees), errors, load, watch, refresh, watchKey, settledVersion }
}
