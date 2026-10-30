import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import type { CourseTree } from '../../types'
import type { NotebookRelation } from './types'
import { projectRelations } from './notebookRelations'
import { useNotebookRelationJobs } from './useNotebookRelationJobs'
import { growthLedger } from '../tree/growth/ledger'

export function useNotebookRelations(trees: CourseTree[], settledVersion: number,
  watchKey: string, refreshDirectories: (ids?: string[]) => Promise<unknown>) {
  const [records, setRecords] = useState<NotebookRelation[]>([])
  const [error, setError] = useState<string>()
  const generation = useRef(0)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; generation.current++ }
  }, [])
  const refresh = useCallback(async () => {
    const request = ++generation.current
    try {
      const rows = await api.getForestRelations()
      if (mounted.current && request === generation.current) {
        growthLedger.observeRelations(rows)
        setRecords(rows)
        setError(undefined)
      }
      return rows
    } catch (cause) {
      if (mounted.current && request === generation.current) {
        setError(cause instanceof Error ? cause.message : '关联读取失败')
      }
    }
  }, [])
  useEffect(() => {
    void refresh()
    const visible = () => { if (document.visibilityState !== 'hidden') void refresh() }
    window.addEventListener('focus', visible)
    document.addEventListener('visibilitychange', visible)
    return () => {
      window.removeEventListener('focus', visible)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [refresh, settledVersion])
  const relations = useMemo(() => projectRelations(records, trees), [records, trees])
  const jobs = useNotebookRelationJobs(watchKey, settledVersion, refresh, refreshDirectories)
  return {
    records, relations, error: error ?? jobs.error, refresh,
    jobs: jobs.jobs, track: jobs.track, discoverJobs: jobs.discoverJobs,
  }
}
