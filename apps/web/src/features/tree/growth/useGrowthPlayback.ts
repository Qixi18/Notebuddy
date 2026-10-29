import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import type { CourseTree } from '../../../types'
import { canPlayGrowth, growthLedger, sectionGrowthKey, treeGrowthEnabled } from './ledger'

<<<<<<< HEAD
export type GrowthAnimations = { courses: Set<string>; books: Set<string>; sections: Set<string> }
const EMPTY: GrowthAnimations = { courses: new Set(), books: new Set(), sections: new Set() }
=======
export type GrowthAnimations = { books: Set<string>; sections: Set<string> }
const EMPTY: GrowthAnimations = { books: new Set(), sections: new Set() }
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
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

<<<<<<< HEAD
function growthBlocked(): boolean {
  return document.visibilityState === 'hidden'
    || Boolean(document.querySelector('[role="dialog"], .modal-backdrop'))
}

export function useGrowthBlocked(): boolean {
  const [blocked, setBlocked] = useState(growthBlocked)
  useEffect(() => {
    const update = () => setBlocked(growthBlocked())
    const observer = new MutationObserver(update)
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['role', 'class'] })
    document.addEventListener('visibilitychange', update)
    update()
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update) }
  }, [])
  return blocked
}

=======
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
/**
 * Converts new directory entries into short-lived visual receipts. Storage keeps
 * IDs only; Notebook text and edit state never enter the growth ledger.
 */
export function useGrowthPlayback(trees: CourseTree[], visibleCourseIds: string[], courseIds: string[]): GrowthAnimations {
  const version = useSyncExternalStore(growthLedger.subscribe, growthLedger.snapshot, () => 0)
  const reduced = useReducedMotion()
<<<<<<< HEAD
  const blocked = useGrowthBlocked()
=======
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
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
<<<<<<< HEAD
    if (blocked || growthBlocked()) return
    const courses = new Set<string>()
    const books = new Set<string>()
    const sections = new Set<string>()
    const consumed = pending.filter(event => {
      if (event.kind === 'relation') return false
      if (!canPlayGrowth(enabled, reduced, visible.has(event.courseId))) return false
      if (event.kind === 'course') courses.add(event.courseId)
      else if (event.kind === 'notebook') books.add(event.notebookId)
=======
    const books = new Set<string>()
    const sections = new Set<string>()
    const consumed = pending.filter(event => {
      if (!canPlayGrowth(enabled, reduced, visible.has(event.courseId))) return false
      if (event.kind === 'notebook') books.add(event.notebookId)
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
      else sections.add(sectionGrowthKey(event.notebookId, event.id))
      return true
    })
    if (!consumed.length) return
    growthLedger.consume(consumed)
    setActive(previous => ({
<<<<<<< HEAD
      courses: new Set([...previous.courses, ...courses]),
      books: new Set([...previous.books, ...books]),
      sections: new Set([...previous.sections, ...sections]),
    }))
  }, [version, visible, reduced, blocked])

  useEffect(() => {
    if (!active.courses.size && !active.books.size && !active.sections.size) return
    const timer = window.setTimeout(() => setActive(EMPTY), 1600)
=======
      books: new Set([...previous.books, ...books]),
      sections: new Set([...previous.sections, ...sections]),
    }))
  }, [version, visible, reduced])

  useEffect(() => {
    if (!active.books.size && !active.sections.size) return
    const timer = window.setTimeout(() => setActive(EMPTY), 650)
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
    return () => window.clearTimeout(timer)
  }, [active])
  return enabled && !reduced ? active : EMPTY
}
