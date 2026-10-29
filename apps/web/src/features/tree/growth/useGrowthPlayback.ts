import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import type { CourseTree } from '../../../types'
import { canPlayGrowth, growthLedger, sectionGrowthKey, treeGrowthEnabled } from './ledger'

export type GrowthAnimations = { books: Set<string>; sections: Set<string> }
const EMPTY: GrowthAnimations = { books: new Set(), sections: new Set() }
const enabled = treeGrowthEnabled(import.meta.env.VITE_TREE_GROWTH_ENABLED)

function reducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(reducedMotion)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(query.matches)
    update()
    query.addEventListener?.('change', update)
    return () => query.removeEventListener?.('change', update)
  }, [])
  return reduced
}

/**
 * Converts new directory entries into short-lived visual receipts. Storage keeps
 * IDs only; Notebook text and edit state never enter the growth ledger.
 */
export function useGrowthPlayback(trees: CourseTree[], visibleCourseIds: string[], courseIds: string[]): GrowthAnimations {
  const version = useSyncExternalStore(growthLedger.subscribe, growthLedger.snapshot, () => 0)
  const reduced = useReducedMotion()
  const [active, setActive] = useState<GrowthAnimations>(EMPTY)
  const visibleKey = visibleCourseIds.join('|')
  const courseKey = courseIds.join('|')
  const visible = useMemo(() => new Set(visibleCourseIds), [visibleKey])

  useEffect(() => {
    if (!enabled) return
    growthLedger.observeCourses(courseIds)
    for (const tree of trees) growthLedger.observeDirectory(tree)
  }, [trees, courseKey])

  useEffect(() => {
    if (!enabled) return
    const pending = growthLedger.pending()
    if (reduced) {
      growthLedger.consume(pending)
      setActive(EMPTY)
      return
    }
    const books = new Set<string>()
    const sections = new Set<string>()
    const consumed = pending.filter(event => {
      if (!canPlayGrowth(enabled, reduced, visible.has(event.courseId))) return false
      if (event.kind === 'notebook') books.add(event.notebookId)
      else sections.add(sectionGrowthKey(event.notebookId, event.id))
      return true
    })
    if (!consumed.length) return
    growthLedger.consume(consumed)
    setActive(previous => ({
      books: new Set([...previous.books, ...books]),
      sections: new Set([...previous.sections, ...sections]),
    }))
  }, [version, visible, reduced])

  useEffect(() => {
    if (!active.books.size && !active.sections.size) return
    const timer = window.setTimeout(() => setActive(EMPTY), 650)
    return () => window.clearTimeout(timer)
  }, [active])
  return enabled && !reduced ? active : EMPTY
}
