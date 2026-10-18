import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import { CurriculumImportPanel } from '../features/forest/CurriculumImportPanel'
import { ForestCoursePanel } from '../features/forest/ForestCoursePanel'
import { ForestRelationsPanel } from '../features/forest/ForestRelationsPanel'
import { KnowledgeTreeScene, type KnowledgeTreeView } from '../features/tree/KnowledgeTreeScene'
import { NotebookRootMenu } from '../features/notebook/NotebookRootMenu'
import { useAutomaticVines } from '../features/forest/useAutomaticVines'
import { useTreeDirectories } from '../features/forest/useTreeDirectories'
import { readSceneSnapshot, saveSceneSnapshot } from '../features/tree/snapshot'
import { notebookPath } from '../features/notebook/navigation'
import type { ForestCourse } from '../features/forest/types'
import type { NotebookSection } from '../types'
import '../features/forest/forest.css'

type SearchResult = { course_id: string; course_name: string; notebook_id: string | null; note_id: string; title: string; material_id: string | null }
export function ForestPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useSearchParams()
  const { refreshCourses } = useWorkspace()
  const restored = useRef(readSceneSnapshot('forest')).current
  const [courses, setCourses] = useState<ForestCourse[]>([])
  const [focusId, setFocusId] = useState(query.get('course') ?? restored?.view?.focusedCourseId)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [expanded, setExpanded] = useState(new Set<string>())
  const [root, setRoot] = useState<string>()
  const [dialog, setDialog] = useState<'import' | 'relations'>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searchError, setSearchError] = useState<string>()
  const [searching, setSearching] = useState(false)
  const [selectedRelation, setSelectedRelation] = useState<string | undefined>(query.get('relation') ?? undefined)
  const directories = useTreeDirectories()
  const vines = useAutomaticVines(directories.watchKey, directories.settledVersion, directories.refresh)
  const { relations } = vines
  const [dismissedJob, setDismissedJob] = useState<string>()
  const job = Object.entries(vines.jobs).find(([id, value]) => id === focusId && value.id !== dismissedJob)?.[1] ?? Object.values(vines.jobs).find(value => value.id !== dismissedJob && ['pending', 'processing', 'failed'].includes(value.status))
  const [visibleIds, setVisibleIds] = useState<string[]>([])
  const visibleDirectories = useCallback((ids: string[]) => { setVisibleIds(ids); directories.watch(ids) }, [directories.watch])
  const pins = relations.filter(relation => relation.status === 'confirmed' && !relation.stale && visibleIds.includes(relation.source_course_id) && visibleIds.includes(relation.target_course_id)).slice(0, 6).flatMap(relation => [relation.source_note_id, relation.target_note_id])
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const reload = useCallback(async () => {
    void directories.refresh()
    const [forest] = await Promise.allSettled([api.getForest(), vines.refresh()])
    if (!mounted.current) return
    if (forest.status === 'fulfilled') setCourses(forest.value.courses)
    else setError(forest.reason instanceof Error ? forest.reason.message : '森林读取失败')
    setLoading(false)
  }, [directories.refresh, vines.refresh])
  useEffect(() => { void reload() }, [reload])
  useEffect(() => { if (query.get('course')) setFocusId(query.get('course')!) }, [query])
  useEffect(() => { if (query.get('relation')) setSelectedRelation(query.get('relation')!) }, [query])
  useEffect(() => {
    const selected = relations.find(relation => relation.id === selectedRelation && relation.status === 'confirmed' && !relation.stale)
    if (selected) directories.load([selected.source_course_id, selected.target_course_id])
  }, [selectedRelation, relations, directories.load])
  useEffect(() => {
    let active = true
    const text = search.trim()
    setSearchError(undefined)
    if (!text) { setResults([]); setSearching(false); return }
    setSearching(true)
    const timer = setTimeout(() => {
      void api.searchForest(text).then(items => { if (active) { setResults(items); directories.load([...new Set(items.map(item => item.course_id))]) } }).catch((cause: unknown) => { if (active) { setResults([]); setSearchError(cause instanceof Error ? cause.message : '搜索失败') } }).finally(() => { if (active) setSearching(false) })
    }, 250)
    return () => { active = false; clearTimeout(timer) }
  }, [search, directories.load])
  const focusCourse = courses.find(course => course.course_id === focusId)
  const courseTree = directories.trees.find(tree => tree.course_id === focusId)
  const [panelBookId, setPanelBookId] = useState('')
  const panelBook = courseTree?.notebooks.find(book => book.id === panelBookId) ?? courseTree?.notebooks[0]
  const returnState = { sceneReturn: focusId ? `/forest?course=${encodeURIComponent(focusId)}` : '/forest', sceneEntry: location.key }
  function openNote(courseId: string, notebookId: string, section: Pick<NotebookSection, 'id' | 'material_id'>) { navigate(notebookPath(courseId, section, undefined, notebookId), { state: returnState }) }
  function focus(id: string) { setFocusId(id); directories.load([id]); setQuery({ course: id }, { replace: true }); setSearch('') }
  const rememberView = (view: KnowledgeTreeView) => saveSceneSnapshot('forest', { view, courseIds: courses.map(course => course.course_id) })
  return <div className="forest-page">
    <header className="forest-header"><div className="forest-heading"><div><h1>知识森林</h1><p>沿着学期，让知识慢慢生长</p></div></div><div className="forest-header-actions"><button onClick={() => { setSettingsOpen(true); if (!focusId && courses[0]) focus(courses[0].course_id) }}>课程设置</button><button onClick={() => setDialog('relations')}>跨课藤蔓</button><button className="forest-action" onClick={() => setDialog('import')}>导入培养方案</button></div></header>
    <div className="forest-surface">
      <KnowledgeTreeScene courses={courses} trees={directories.trees} initialView={restored?.view} onViewChange={rememberView} focusCourseId={focusId} onFocusCourse={setFocusId} search={search} relations={relations} pinnedNoteIds={pins} selectedRelationId={selectedRelation} onVisibleCourseIdsChange={visibleDirectories}
        onRoot={setRoot} onNotebook={(courseId, notebookId) => navigate(notebookPath(courseId, undefined, undefined, notebookId), { state: returnState })} onNote={openNote} onRelation={relation => { setSelectedRelation(relation.id); setDialog('relations') }} />
      <div className="forest-search"><label><input aria-label="搜索课程或知识点" placeholder="寻找课程或知识点" value={search} onChange={event => setSearch(event.target.value)} /></label>{search.trim() && <div className="forest-search-results" aria-label="搜索结果">
        {courses.filter(course => course.name.toLowerCase().includes(search.toLowerCase())).slice(0, 8).map(course => <button key={course.course_id} onClick={() => focus(course.course_id)}><span>课程</span><strong>{course.name}</strong></button>)}
        {results.map(item => <button key={item.note_id} onClick={() => item.notebook_id ? openNote(item.course_id, item.notebook_id, { id: item.note_id, material_id: item.material_id }) : navigate(`/courses/${item.course_id}/notes/${item.note_id}`, { state: returnState })}><span>笔记</span><strong>{item.title}</strong><small>{item.course_name}</small></button>)}
        {searching && <p role="status">寻找知识点…</p>}{searchError && <p role="alert">{searchError}</p>}
      </div>}</div>
      <div className="forest-legend" aria-label="课程学习状态"><span><i className="forest-state-planned" />未开始</span><span><i className="forest-state-learning" />在学</span><span><i className="forest-state-completed" />已完成</span></div>
      {loading && <p role="status" className="forest-scene-message">正在打开森林…</p>}
      {(error || vines.error) && <div className="forest-scene-error" role="alert">{error ?? vines.error}<button onClick={() => { setError(undefined); void reload() }}>重新读取</button></div>}
      {Object.keys(directories.errors).length > 0 && <div className="forest-outline-error" role="alert">部分课程目录读取失败<button onClick={() => directories.load(Object.keys(directories.errors))}>重试目录</button></div>}
      {!loading && !courses.length && !error && <div className="forest-scene-empty"><h2>你的森林，从一门课程开始</h2><button className="forest-action" onClick={() => setDialog('import')}>导入培养方案</button><button onClick={() => navigate('/', { state: { openCreateCourse: true } })}>手动创建课程</button></div>}
      {settingsOpen && focusCourse && <div className="forest-settings-wrap"><label>设置课程<select value={focusId} onChange={event => focus(event.target.value)}>{courses.map(course => <option key={course.course_id} value={course.course_id}>{course.name}</option>)}</select></label>
        {courseTree && <label>笔记本<select value={panelBook?.id ?? ''} onChange={event => setPanelBookId(event.target.value)}>{courseTree.notebooks.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>}
        <ForestCoursePanel key={`${focusId}:${focusCourse.revision}`} course={focusCourse} book={panelBook} expanded={expanded} onExpand={id => setExpanded(current => current.has(id) ? new Set() : new Set([id]))} onClose={() => setSettingsOpen(false)} onUpdated={next => { setCourses(current => current.map(course => course.course_id === next.course_id ? next : course)); void refreshCourses() }} onOpen={section => panelBook && openNote(focusCourse.course_id, panelBook.id, section)} onFit={() => { setSettingsOpen(false); setFocusId(undefined); setTimeout(() => setFocusId(focusCourse.course_id), 0) }} onJob={next => vines.track(focusCourse.course_id, next)} />
      </div>}
      <details className="forest-minimap"><summary>森林地图 · {courses.length} 门课程</summary><div className="forest-course-map">{courses.map(course => <button key={course.course_id} aria-label={`地图定位${course.name}`} onClick={() => focus(course.course_id)}>{course.semester ? `第${course.semester}学期 · ` : ''}{course.name}</button>)}</div></details>
      {job && <div className={`forest-job-toast forest-job-${job.status}`} role="status"><span>{job.status === 'failed' ? job.error_message ?? '关联任务失败' : job.status === 'completed' ? '关联任务已完成' : `正在寻找跨课程关联 · ${job.progress}%`}</span>{job.status === 'failed' && <button onClick={() => void api.retryForestJob(job.id).then(next => { const courseId = Object.keys(vines.jobs).find(id => vines.jobs[id].id === job.id); if (courseId) vines.track(courseId, next) }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '重试失败'))}>重试</button>}<button onClick={() => setDialog('relations')}>查看藤蔓</button><button aria-label="关闭任务提示" onClick={() => setDismissedJob(job.id)}>×</button></div>}
    </div>
    {root && <NotebookRootMenu courseId={root} courseName={courses.find(course => course.course_id === root)?.name ?? '课程'} onClose={() => setRoot(undefined)} returnState={returnState} />}
    {dialog === 'relations' && <ForestRelationsPanel relations={relations} courses={courses} onLocate={relation => { setSelectedRelation(relation.id); directories.load([relation.source_course_id, relation.target_course_id]); setDialog(undefined) }} onChange={() => void reload()} onClose={() => setDialog(undefined)} />}
    {dialog === 'import' && <CurriculumImportPanel courses={courses} onConfirmed={() => { void reload(); void refreshCourses() }} onClose={() => setDialog(undefined)} />}
  </div>
}
