import type { CourseTree, NotebookRead, NotebookSection } from '../../../types'
<<<<<<< HEAD
import type { NotebookRelation } from '../../forest/types'

export type GrowthEvent =
  | { kind: 'course'; id: string; courseId: string }
  | { kind: 'notebook'; id: string; courseId: string; notebookId: string }
  | { kind: 'section'; id: string; courseId: string; notebookId: string }
  | { kind: 'relation'; id: string; courseId: string; targetCourseId: string }
=======

export type GrowthEvent =
  | { kind: 'notebook'; id: string; courseId: string; notebookId: string }
  | { kind: 'section'; id: string; courseId: string; notebookId: string }
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>
type SavedLedger = { version: 2; seen: string[]; scopes: string[]; events: GrowthEvent[] }
const STORAGE_KEY = 'notebuddy.tree.growth.v2'
const LEGACY_STORAGE_KEY = 'notebuddy.tree.growth.v1'
const MAX_SEEN = 5000
const MAX_EVENTS = 100

const notebookKey = (id: string) => `notebook:${id}`
<<<<<<< HEAD
const courseKey = (id: string) => `course:${id}`
const sectionKey = (notebookId: string, blockId: string) => `section:${sectionGrowthKey(notebookId, blockId)}`
const directoryKey = (courseId: string) => `directory:${courseId}`
const relationKey = (id: string) => `relation:${id}`
=======
const sectionKey = (notebookId: string, blockId: string) => `section:${sectionGrowthKey(notebookId, blockId)}`
const directoryKey = (courseId: string) => `directory:${courseId}`
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
const validStrings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string')

/** A section is identified by its owner and stable Tiptap block id, never by a legacy Note id. */
export function sectionGrowthKey(notebookId: string, blockId: string): string {
  return JSON.stringify([notebookId, blockId])
}

export function treeGrowthEnabled(value: string | undefined): boolean {
<<<<<<< HEAD
  return value !== 'false'
=======
  return value === 'true'
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
}

export function canPlayGrowth(enabled: boolean, reducedMotion: boolean, visible: boolean): boolean {
  return enabled && !reducedMotion && visible
}

function sections(book: NotebookRead): NotebookSection[] {
  return [...book.chapters.flatMap(chapter => chapter.sections), ...book.historical_sections]
}

function browserStorage(): Storage | undefined {
  try {
    return typeof sessionStorage === 'undefined' ? undefined : sessionStorage
  } catch {
    return undefined
  }
}

/** Stores only seen IDs and short-lived animation receipts, never Notebook text. */
export class GrowthLedger {
  private seen = new Set<string>()
  private scopes = new Set<string>()
  private events = new Map<string, GrowthEvent>()
  private listeners = new Set<() => void>()
  private version = 0
  private raw: string | null = null
  private unavailable = false
  private readonly storage: Storage | undefined

  constructor(storage: Storage | undefined = browserStorage()) {
    this.storage = storage
    this.readStorage()
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  snapshot = () => this.version
  pending = () => [...this.events.values()]

  private readStorage() {
    if (!this.storage || this.unavailable) return
    try {
      const raw = this.storage.getItem(STORAGE_KEY)
      if (raw === this.raw) return
      this.raw = raw
      this.seen.clear()
      this.scopes.clear()
      this.events.clear()
      const saved = JSON.parse(raw ?? 'null') as Partial<SavedLedger> | null
      if (saved?.version !== 2 || !validStrings(saved.seen) || !validStrings(saved.scopes) || !Array.isArray(saved.events)) return
      this.seen = new Set(saved.seen.slice(-MAX_SEEN))
      this.scopes = new Set(saved.scopes)
      for (const event of saved.events) {
<<<<<<< HEAD
        if (!event || !['course', 'notebook', 'section', 'relation'].includes(event.kind) || typeof event.id !== 'string' || typeof event.courseId !== 'string') continue
        if (event.kind === 'relation') {
          if (typeof event.targetCourseId !== 'string') continue
          this.events.set(relationKey(event.id), event)
          continue
        }
        if (event.kind === 'course') {
          this.events.set(courseKey(event.id), event)
          continue
        }
        if (typeof event.notebookId !== 'string') continue
=======
        if (!event || (event.kind !== 'notebook' && event.kind !== 'section') ||
          typeof event.id !== 'string' || typeof event.courseId !== 'string' || typeof event.notebookId !== 'string') continue
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
        const key = event.kind === 'section' ? sectionKey(event.notebookId, event.id) : notebookKey(event.id)
        this.events.set(key, event)
      }
    } catch {
      this.unavailable = true
    }
  }

  private serialize(): string {
    return JSON.stringify({
      version: 2,
      seen: [...this.seen].slice(-MAX_SEEN),
      scopes: [...this.scopes],
      events: [...this.events.values()].slice(-MAX_EVENTS),
    } satisfies SavedLedger)
  }

  private update(action: () => void) {
    this.readStorage()
    const before = this.serialize()
    action()
    while (this.seen.size > MAX_SEEN) this.seen.delete(this.seen.values().next().value!)
    while (this.events.size > MAX_EVENTS) this.events.delete(this.events.keys().next().value!)
    const after = this.serialize()
    if (after === before) return
    this.raw = after
    try {
      if (!this.unavailable) this.storage?.setItem(STORAGE_KEY, after)
    } catch {
      this.unavailable = true
    }
    this.version++
    for (const listener of this.listeners) listener()
  }

  private add(event: GrowthEvent, key: string) {
    if (this.seen.has(key)) return
    this.events.set(key, event)
    this.seen.add(key)
  }

  /** The first directory response seeds a baseline; later responses detect additions. */
  observeDirectory(tree: CourseTree) {
    this.update(() => {
      const directory = directoryKey(tree.course_id)
      const initialized = this.scopes.has(directory)
<<<<<<< HEAD
      this.seen.add(courseKey(tree.course_id))
=======
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
      const liveBooks = new Set<string>()
      const liveSections = new Set<string>()

      for (const book of tree.notebooks.filter(row => row.course_id === tree.course_id)) {
        liveBooks.add(book.id)
        const bookKey = notebookKey(book.id)
        const knownBook = this.seen.has(bookKey)
        if (initialized && !knownBook) this.add({ kind: 'notebook', id: book.id, courseId: tree.course_id, notebookId: book.id }, bookKey)
        else this.seen.add(bookKey)

        const bookInitialized = this.scopes.has(`book:${book.id}`)
        for (const section of sections(book)) {
          const blockId = section.block_id
          // Old Note IDs are intentionally not promoted to document block IDs.
          if (!blockId) continue
          const key = sectionKey(book.id, blockId)
          liveSections.add(key)
          if (initialized && bookInitialized) {
            this.add({ kind: 'section', id: blockId, courseId: tree.course_id, notebookId: book.id }, key)
          } else {
            this.seen.add(key)
          }
        }
        this.scopes.add(`book:${book.id}`)
      }

      // A newly observed Notebook gets one branch event. Its first set of sections
      // is baseline, so they cannot produce duplicate leaf events.
      for (const [key, event] of this.events) {
<<<<<<< HEAD
        if (event.kind === 'relation' || event.kind === 'course' || event.courseId !== tree.course_id) continue
=======
        if (event.courseId !== tree.course_id) continue
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
        const live = event.kind === 'notebook' ? liveBooks.has(event.notebookId) : liveSections.has(key)
        if (!live) this.events.delete(key)
      }
      this.scopes.add(directory)
    })
  }

  observeCourses(courseIds: string[]) {
    this.update(() => {
      const current = new Set(courseIds)
<<<<<<< HEAD
      const initialized = this.scopes.has('courses')
      for (const id of courseIds) {
        const key = courseKey(id)
        if (initialized) this.add({ kind: 'course', id, courseId: id }, key)
        else this.seen.add(key)
      }
      this.scopes.add('courses')
      for (const [key, event] of this.events) if (!current.has(event.courseId) || event.kind === 'relation' && !current.has(event.targetCourseId)) this.events.delete(key)
    })
  }

  /** First relation response is a baseline; later new IDs get one vine receipt. */
  observeRelations(rows: NotebookRelation[]) {
    this.update(() => {
      const scope = 'relations'
      const initialized = this.scopes.has(scope)
      const live = new Set<string>()
      for (const row of rows) {
        if (row.stale || row.origin !== 'ai' && row.origin !== 'manual') continue
        const key = relationKey(row.id)
        live.add(key)
        if (initialized && !this.seen.has(key)) this.add({ kind: 'relation', id: row.id, courseId: row.source_course_id, targetCourseId: row.target_course_id }, key)
        else this.seen.add(key)
      }
      for (const [key, event] of this.events) if (event.kind === 'relation' && !live.has(key)) this.events.delete(key)
      this.scopes.add(scope)
=======
      for (const [key, event] of this.events) if (!current.has(event.courseId)) this.events.delete(key)
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
    })
  }

  consume(events: GrowthEvent[]) {
    this.update(() => {
      for (const event of events) {
<<<<<<< HEAD
        this.events.delete(event.kind === 'relation' ? relationKey(event.id) : event.kind === 'course' ? courseKey(event.id) : event.kind === 'section' ? sectionKey(event.notebookId, event.id) : notebookKey(event.id))
=======
        this.events.delete(event.kind === 'section' ? sectionKey(event.notebookId, event.id) : notebookKey(event.id))
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
      }
    })
  }
}

export const growthLedger = new GrowthLedger()
export const LEGACY_GROWTH_STORAGE_KEY = LEGACY_STORAGE_KEY
