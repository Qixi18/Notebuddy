import type { DocNode } from './document'

export type NotebookDraft = {
  key: string
  content: DocNode
  revision: number
  updatedAt: string
}

const DB_NAME = 'notebuddy-editor'
const STORE = 'drafts'

function draftKey(courseId: string, notebookId: string): string {
  return `notebook:${courseId}:${notebookId}`
}

function openDatabase(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') { resolve(null); return }
    try {
      const request = indexedDB.open(DB_NAME, 1)
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: 'key' })
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}

export async function readDraft(courseId: string, notebookId: string): Promise<NotebookDraft | null> {
  const key = draftKey(courseId, notebookId)
  const database = await openDatabase()
  if (!database) return readFallback(key)
  return new Promise((resolve) => {
    const transaction = database.transaction(STORE, 'readonly')
    const request = transaction.objectStore(STORE).get(key)
    request.onsuccess = () => resolve((request.result as NotebookDraft | undefined) ?? readFallback(key))
    request.onerror = () => resolve(readFallback(key))
    transaction.oncomplete = () => database.close()
  })
}

export async function writeDraft(courseId: string, notebookId: string, content: DocNode, revision: number): Promise<void> {
  const draft: NotebookDraft = { key: draftKey(courseId, notebookId), content, revision, updatedAt: new Date().toISOString() }
  const database = await openDatabase()
  if (!database) { writeFallback(draft); return }
  await new Promise<void>((resolve) => {
    const transaction = database.transaction(STORE, 'readwrite')
    transaction.objectStore(STORE).put(draft)
    transaction.oncomplete = () => { database.close(); resolve() }
    transaction.onerror = () => { writeFallback(draft); database.close(); resolve() }
  })
}

export async function clearDraft(courseId: string, notebookId: string): Promise<void> {
  const key = draftKey(courseId, notebookId)
  writeFallback(null, key)
  const database = await openDatabase()
  if (!database) return
  await new Promise<void>((resolve) => {
    const transaction = database.transaction(STORE, 'readwrite')
    transaction.objectStore(STORE).delete(key)
    transaction.oncomplete = () => { database.close(); resolve() }
    transaction.onerror = () => { database.close(); resolve() }
  })
}

type FallbackDraft = Omit<NotebookDraft, 'key'>
const FALLBACK_PREFIX = 'notebuddy-draft:'

function readFallback(key: string): NotebookDraft | null {
  try {
    const raw = localStorage.getItem(FALLBACK_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as FallbackDraft
    return { key, ...parsed }
  } catch {
    return null
  }
}

function writeFallback(draft: NotebookDraft | null, key = draft?.key): void {
  if (!key) return
  try {
    if (!draft) localStorage.removeItem(FALLBACK_PREFIX + key)
    else localStorage.setItem(FALLBACK_PREFIX + key, JSON.stringify({ content: draft.content, revision: draft.revision, updatedAt: draft.updatedAt }))
  } catch {
    // Storage may be unavailable in private windows; the in-memory editor still works.
  }
}
