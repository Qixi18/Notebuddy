import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { matchPath, useLocation } from 'react-router-dom'

import { api } from '../../api'
import { useConversation } from '../conversation/useConversation'
import { useNoteEditor } from '../notes/useNoteEditor'
import { mergeNotebookNotes } from '../notebook/navigation'
import { useTeacherCharacter } from '../persona/useTeacherCharacter'
import { resolveConversationCourseId } from './currentCourse'
import type { Course, Job, KnowledgeGraph, Material, Note, Page } from '../../types'

const isNotebookRoute = (path: string) => /\/notebooks?($|\/)/.test(path)

const emptyGraph: KnowledgeGraph = { nodes: [], edges: [] }

export function useWorkspaceState() {
  const location = useLocation()
  const courseId = matchPath('/courses/:courseId/*', location.pathname)?.params.courseId
  const currentCourseId = useRef(courseId)
  currentCourseId.current = courseId
  const [courses, setCourses] = useState<Course[]>([])
  const [coursesLoading, setCoursesLoading] = useState(true)
  const [courseContentLoading, setCourseContentLoading] = useState(false)
  const [materials, setMaterials] = useState<Material[]>([])
  const [selectedMaterialId, setSelectedMaterialId] = useState<string>()
  const currentMaterialId = useRef(selectedMaterialId)
  currentMaterialId.current = selectedMaterialId
  const [pages, setPages] = useState<Page[]>([])
  const [selectedPageNumber, setSelectedPageNumber] = useState<number>()
  const requestedSourcePage = useRef<{ materialId: string; page: number | undefined } | undefined>(undefined)
  const openMaterialSource = useCallback((materialId: string, page: number | undefined) => {
    requestedSourcePage.current = currentMaterialId.current === materialId ? undefined : { materialId, page }
    setSelectedMaterialId(materialId)
    setSelectedPageNumber(page)
  }, [])
  const [notes, setNotes] = useState<Note[]>([])
  const upsertNotes = useCallback((incoming: Note[]) => {
    setNotes((current) => mergeNotebookNotes(current, incoming))
  }, [])
  const [selectedNoteId, setSelectedNoteId] = useState<string>()
  const [graph, setGraph] = useState<KnowledgeGraph>(emptyGraph)
  const [job, setJob] = useState<Job>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [documentDirty, setDocumentDirty] = useState(false)

  const [teacherPersona, setTeacherPersona] = useTeacherCharacter()

  const course = courses.find((item) => item.id === courseId)
  const selectedNote = notes.find((note) => note.id === selectedNoteId)
  const { noteDraft, setNoteDraft, editingNote, setEditingNote, noteSaving, noteDirty, saveNote, reloadNote } = useNoteEditor(selectedNote, setNotes, setError)
  /* 悬浮球要在任何页面都能提问，所以要有一个课程落点：URL 课程优先，
     否则落到最近访问过的课程（详见 features/workspace/currentCourse.ts） */
  const conversationCourseId = useMemo(
    () => resolveConversationCourseId(courseId, courses, (key) => localStorage.getItem(key)),
    [courseId, courses],
  )
  const conversation = useConversation(conversationCourseId, teacherPersona)

  useEffect(() => {
    if (!courseId || !course) return
    let active = true
    void api.visitCourse(courseId).then(({ last_opened_at }) => {
      if (!active) return
      setCourses(current => current.map(item => item.id === courseId ? { ...item, last_opened_at } : item))
      try { localStorage.setItem(`notebuddy.course.${courseId}.lastVisited`, last_opened_at) } catch { /* Server remains the recency source. */ }
    }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '课程访问时间保存失败') })
    return () => { active = false }
  }, [courseId, course?.id, location.pathname])

  const refreshCourses = useCallback(async () => {
    try {
      setCoursesLoading(true)
      setCourses(await api.listCourses())
      setError(undefined)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程读取失败')
    } finally {
      setCoursesLoading(false)
    }
  }, [])

  const refreshMaterials = useCallback(async (id: string) => {
    const next = await api.listMaterials(id)
    if (currentCourseId.current !== id) return
    setMaterials(next)
    setSelectedMaterialId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id)
  }, [])

  const refreshPages = useCallback(async (id: string) => {
    const next = await api.listPages(id)
    if (currentMaterialId.current !== id) return
    setPages(next)
    const target = requestedSourcePage.current?.materialId === id ? requestedSourcePage.current.page : undefined
    setSelectedPageNumber((current) => {
      const desired = target ?? current
      return desired && next.some((page) => page.page_number === desired) ? desired : next[0]?.page_number
    })
    if (requestedSourcePage.current?.materialId === id) requestedSourcePage.current = undefined
  }, [])

  const refreshNotes = useCallback(async (id: string) => {
    const next = await api.listNotes(id)
    if (currentCourseId.current !== id) return
    setNotes(next)
    setSelectedNoteId((current) => current && next.some((note) => note.id === current) ? current : next[0]?.id)
  }, [])

  const refreshGraph = useCallback(async (id: string) => {
    const next = await api.getKnowledgeGraph(id)
    if (currentCourseId.current === id) setGraph(next)
  }, [])

  useEffect(() => { void refreshCourses() }, [refreshCourses])

  useEffect(() => {
    if (courseId && !isNotebookRoute(location.pathname)) {
      void refreshNotes(courseId).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '笔记读取失败'))
    }
  }, [courseId, location.pathname, refreshNotes])

  useEffect(() => {
    let active = true
    setMaterials([])
    setPages([])
    setNotes([])
    setGraph(emptyGraph)
    setSelectedMaterialId(undefined)
    setSelectedPageNumber(undefined)
    setSelectedNoteId(undefined)
    requestedSourcePage.current = undefined
    setJob(undefined)
    setCourseContentLoading(Boolean(courseId))

    if (!courseId) return () => { active = false }

    void Promise.all([
      api.listMaterials(courseId),
      isNotebookRoute(location.pathname) ? Promise.resolve([] as Note[]) : api.listNotes(courseId),
      api.getKnowledgeGraph(courseId),
    ]).then(([nextMaterials, nextNotes, nextGraph]) => {
      if (!active) return
      setMaterials(nextMaterials)
      setSelectedMaterialId(nextMaterials[0]?.id)
      setNotes(nextNotes)
      setSelectedNoteId(nextNotes[0]?.id)
      setGraph(nextGraph)
      setError(undefined)
      setCourseContentLoading(false)
    }).catch((cause: unknown) => {
      if (!active) return
      setCourseContentLoading(false)
      const message = cause instanceof Error ? cause.message : '课程内容读取失败'
      if (message.includes('课程不存在')) {
        setError(undefined)
        return
      }
      setError(message)
    })

    return () => { active = false }
  }, [courseId])

  useEffect(() => {
    let active = true
    setPages([])
    setSelectedPageNumber(requestedSourcePage.current?.materialId === selectedMaterialId ? requestedSourcePage.current?.page : undefined)
    setJob(undefined)
    if (!selectedMaterialId) return () => { active = false }
    void refreshPages(selectedMaterialId).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '页面读取失败')
    })
    void api.getLatestMaterialJob(selectedMaterialId).then((latestJob) => { if (active) setJob(latestJob) }).catch(() => { if (active) setJob(undefined) })
    return () => { active = false }
  }, [selectedMaterialId, refreshPages])

  useEffect(() => {
    if (!job || job.status === 'completed' || job.status === 'failed') return
    let active = true
    const timer = window.setInterval(() => {
      void api.getJob(job.id).then(async (nextJob) => {
        if (!active) return
        setJob(nextJob)
        if ((nextJob.status === 'completed' || nextJob.status === 'failed') && courseId) {
          const refreshes = [refreshMaterials(courseId)]
          if (nextJob.status === 'completed') refreshes.push(refreshNotes(courseId), refreshGraph(courseId))
          await Promise.all(refreshes)
        }
      }).catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : '任务状态读取失败')
      })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [job, courseId, refreshMaterials, refreshNotes, refreshGraph])

  async function createCourse(name: string): Promise<Course> {
    const created = await api.createCourse(name)
    setCourses((current) => [created, ...current.filter((item) => item.id !== created.id)])
    return created
  }

  async function uploadMaterial(file: File, lectureTitle: string, topicTitle?: string, allowDuplicate = false, notebookId?: string) {
    if (!courseId) throw new Error('请先选择课程')
    try {
      setBusy(true)
      setError(undefined)
      const result = await api.uploadMaterial(courseId, file, lectureTitle, topicTitle, allowDuplicate, crypto.randomUUID(), notebookId)
      if (currentCourseId.current !== courseId) return
      setJob(result.job)
      setSelectedMaterialId(result.material.id)
      await refreshMaterials(courseId)
      setSelectedMaterialId(result.material.id)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '资料上传失败'
      setError(message)
      throw cause
    } finally {
      setBusy(false)
    }
  }

  async function retryMaterial(materialId: string) {
    try {
      setError(undefined)
      const nextJob = await api.retryMaterial(materialId)
      setJob(nextJob)
      await refreshMaterials(courseId!)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '资料重试失败')
    }
  }

  async function reparseMaterial(materialId: string) {
    try {
      setError(undefined)
      const nextJob = await api.reparseMaterial(materialId)
      setJob(nextJob)
      await refreshMaterials(courseId!)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '资料重解析失败')
    }
  }

  async function requestOCR(materialId: string) {
    try {
      setError(undefined)
      const nextJob = await api.requestOCR(materialId)
      setJob(nextJob)
      await refreshMaterials(courseId!)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'OCR 请求失败')
    }
  }

  const workspace = useMemo(() => ({
    courses,
    courseId,
    course,
    /** 会话实际挂靠的课程：URL 课程，或没有 URL 课程时的最近访问课程 */
    conversationCourseId,
    coursesLoading,
    courseContentLoading,
    materials,
    selectedMaterialId,
    setSelectedMaterialId,
    pages,
    selectedPageNumber,
    setSelectedPageNumber,
    openMaterialSource,
    notes,
    upsertNotes,
    selectedNote,
    setSelectedNoteId,
    noteDraft,
    setNoteDraft,
    editingNote,
    setEditingNote,
    graph,
    job,
    teacherPersona,
    setTeacherPersona,
    conversation,
    busy: busy || conversation.busy,
    noteSaving,
    noteDirty,
    documentDirty,
    setDocumentDirty,
    reloadNote,
    error,
    setError,
    createCourse,
    uploadMaterial,
    retryMaterial,
    reparseMaterial,
    requestOCR,
    saveNote,
    refreshCourses,
    refreshCurrentMaterials: () => courseId ? refreshMaterials(courseId) : Promise.resolve(),
    refreshCurrentNotes: () => courseId ? refreshNotes(courseId) : Promise.resolve(),
  }), [courses, courseId, conversationCourseId, course, coursesLoading, courseContentLoading, materials, selectedMaterialId, pages, selectedPageNumber, notes, selectedNote, noteDraft, editingNote, graph, job, teacherPersona, conversation, busy, noteSaving, noteDirty, documentDirty, reloadNote, error, createCourse, uploadMaterial, retryMaterial, reparseMaterial, requestOCR, saveNote, refreshCourses])

  return workspace
}
