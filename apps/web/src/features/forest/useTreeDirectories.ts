import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { CourseTree } from '../../types'

export function useTreeDirectories() {
  const [trees, setTrees] = useState<Record<string, CourseTree>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const requested = useRef(new Set<string>())
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const load = useCallback((ids: string[]) => {
    for (const id of ids) {
      if (requested.current.has(id)) continue
      requested.current.add(id)
      void api.getCourseTree(id).then(tree => {
        if (!mounted.current) return
        setTrees(current => ({ ...current, [id]: tree }))
        setErrors(current => { const next = { ...current }; delete next[id]; return next })
      }).catch((cause: unknown) => {
        requested.current.delete(id)
        if (mounted.current) setErrors(current => ({ ...current, [id]: cause instanceof Error ? cause.message : '目录读取失败' }))
      })
    }
  }, [])
  return { trees: Object.values(trees), errors, load }
}
