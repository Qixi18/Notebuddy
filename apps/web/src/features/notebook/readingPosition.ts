import { api, ApiError } from '../../api'
import type { NotebookReadingPosition, ReadingPositionUpdate } from '../../types'

export type Position = Omit<ReadingPositionUpdate, 'expected_revision'>
type Writer = { revision: number; chain: Promise<void>; blocked: boolean; pending?: Position; queued: number }
const writers = new Map<string, Writer>()
const cacheKey = (courseId: string, bookId: string) => `notebuddy.reading.pending.${courseId}.${bookId}`
export function pendingPosition(courseId: string, bookId: string): Position | undefined {
  try { return JSON.parse(sessionStorage.getItem(cacheKey(courseId, bookId)) ?? 'null') ?? undefined } catch { return undefined }
}
export function positionWriter(courseId: string, bookId: string, initial: NotebookReadingPosition | null) {
  const key = cacheKey(courseId, bookId)
  let writer = writers.get(key)
  if (!writer) { writer = { revision: initial?.revision ?? 0, chain: Promise.resolve(), blocked: Boolean(pendingPosition(courseId, bookId)), queued: 0 }; writers.set(key, writer) }
  // A server GET may be older than our own in-flight save; never move CAS backwards.
  writer.revision = writer.queued ? Math.max(writer.revision, initial?.revision ?? 0) : initial?.revision ?? 0
  const current = writer
  return {
    save(position: Position): Promise<void> {
      current.queued += 1
      current.pending = position
      try { sessionStorage.setItem(key, JSON.stringify(position)) } catch { /* Saving to the server still works. */ }
      const next = current.chain.then(async () => {
        if (current.blocked) throw new Error('阅读位置保存暂停，请重试保存当前位置。')
        try {
          const saved = await api.saveReadingPosition(courseId, bookId, { ...position, expected_revision: current.revision })
          current.revision = saved.revision
          if (current.pending === position) { current.pending = undefined; sessionStorage.removeItem(key) }
        } catch (cause) {
          current.blocked = true
          if (cause instanceof ApiError && cause.status === 409) throw new Error('阅读位置已在其他窗口更新；当前进度已暂存，请选择重试保存当前位置。')
          throw new Error('阅读位置保存失败；当前进度已暂存，请重试。')
        }
      })
      current.chain = next.catch(() => undefined).finally(() => { current.queued -= 1 })
      return next
    },
    async resume() {
      await current.chain
      const latest = await api.getReadingPosition(courseId, bookId)
      current.revision = latest?.revision ?? 0
      current.blocked = false
    },
  }
}
