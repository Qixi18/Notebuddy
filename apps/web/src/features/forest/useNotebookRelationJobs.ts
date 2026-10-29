import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { ForestJob, NotebookRelation } from './types'

/** Discover only visible courses and stop polling every terminal task. */
export function useNotebookRelationJobs(watchKey: string, settledVersion: number,
  refresh: () => Promise<NotebookRelation[] | undefined>,
  refreshDirectories: (ids?: string[]) => Promise<unknown>) {
  const [jobs, setJobs] = useState<Record<string, ForestJob>>({})
  const [error, setError] = useState<string>()
  const epochs = useRef<Record<string, number>>({})
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const discoverJobs = useCallback(async () => {
    if (document.visibilityState === 'hidden') return
    await Promise.all(watchKey.split('|').filter(Boolean).map(async id => {
      const epoch = (epochs.current[id] ?? 0) + 1
      epochs.current[id] = epoch
      try {
        const job = await api.getLatestForestJob(id)
        if (mounted.current && epochs.current[id] === epoch) {
          setJobs(current => {
            const next = { ...current }
            if (job) next[id] = job
            else delete next[id]
            return next
          })
          setError(undefined)
        }
      } catch (cause) {
        if (mounted.current && epochs.current[id] === epoch) {
          setError(cause instanceof Error ? cause.message : '关联任务读取失败')
        }
      }
    }))
  }, [watchKey])
  useEffect(() => {
    void discoverJobs()
    document.addEventListener('visibilitychange', discoverJobs)
    return () => { document.removeEventListener('visibilitychange', discoverJobs) }
  }, [discoverJobs, settledVersion])

  const pendingKey = watchKey.split('|').filter(id => jobs[id]
    && ['pending', 'processing'].includes(jobs[id].status)).map(id => `${id}:${jobs[id].id}`).join('|')
  useEffect(() => {
    if (!pendingKey) return
    let active = true, inFlight = false
    const timer = window.setInterval(() => {
      if (inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      void Promise.all(pendingKey.split('|').map(async pair => {
        const [courseId, jobId] = pair.split(':')
        const epoch = epochs.current[courseId]
        try {
          const job = await api.getForestJob(jobId)
          if (!active || epochs.current[courseId] !== epoch) return
          setJobs(current => current[courseId]?.id === jobId
            ? { ...current, [courseId]: job } : current)
          setError(undefined)
          if (job.status === 'completed' || job.status === 'failed') {
            const rows = await refresh()
            if (active) {
              const changed = new Set([courseId, ...(rows ?? [])
                .filter(row => row.source_course_id === courseId || row.target_course_id === courseId)
                .flatMap(row => [row.source_course_id, row.target_course_id])])
              await refreshDirectories(watchKey.split('|').filter(id => changed.has(id)))
            }
          }
        } catch (cause) {
          if (active) setError(cause instanceof Error ? cause.message : '关联任务读取失败')
        }
      })).finally(() => { inFlight = false })
    }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [pendingKey, watchKey, refresh, refreshDirectories])
  const track = useCallback((courseId: string, job: ForestJob) => {
    epochs.current[courseId] = (epochs.current[courseId] ?? 0) + 1
    setJobs(current => ({ ...current, [courseId]: job }))
  }, [])
  return { jobs, error, track, discoverJobs }
}
