import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { CrossCourseRelation, ForestJob } from './types'

// The material poller remains in useTreeDirectories. Only visible/neighbor
// relation jobs are discovered here; terminal jobs stop being polled.
export function useAutomaticVines(watchKey: string, settledVersion: number, refreshDirectories: (ids?: string[]) => Promise<unknown>) {
  const [relations, setRelations] = useState<CrossCourseRelation[]>([])
  const [jobs, setJobs] = useState<Record<string, ForestJob>>({})
  const [error, setError] = useState<string>()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const refresh = useCallback(async () => {
    try {
      const rows = await api.getForestRelations()
      if (mounted.current) { setRelations(rows); setError(undefined) }
      return rows
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : '关联读取失败') }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    let active = true
    const discover = async () => {
      if (document.visibilityState === 'hidden') return
      await Promise.all(watchKey.split('|').filter(Boolean).map(async id => {
        try {
          const job = await api.getLatestForestJob(id)
          if (active && job) setJobs(current => ({ ...current, [id]: job }))
        } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : '关联任务读取失败') }
      }))
      if (active) void refresh()
    }
    void discover()
    document.addEventListener('visibilitychange', discover)
    return () => { active = false; document.removeEventListener('visibilitychange', discover) }
  }, [watchKey, settledVersion, refresh])
  const pendingKey = watchKey.split('|').filter(id => jobs[id] && ['pending', 'processing'].includes(jobs[id].status)).map(id => `${id}:${jobs[id].id}`).join('|')
  useEffect(() => {
    if (!pendingKey) return
    let active = true, inFlight = false
    const timer = window.setInterval(() => {
      if (inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      void Promise.all(pendingKey.split('|').map(async pair => {
        const [courseId, jobId] = pair.split(':')
        try {
          const job = await api.getForestJob(jobId)
          if (!active) return
          setJobs(current => ({ ...current, [courseId]: job }))
          if (job.status === 'completed' || job.status === 'failed') {
            const rows = await refresh()
            const changed = new Set([courseId, ...(rows ?? []).filter(row => row.source_course_id === courseId || row.target_course_id === courseId).flatMap(row => [row.source_course_id, row.target_course_id])])
            await refreshDirectories(watchKey.split('|').filter(id => changed.has(id)))
          }
        } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : '关联任务读取失败') }
      })).finally(() => { inFlight = false })
    }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [pendingKey, refresh, refreshDirectories, watchKey])
  const track = useCallback((courseId: string, job: ForestJob) => setJobs(current => ({ ...current, [courseId]: job })), [])
  return { relations, jobs, error, refresh, track }
}
