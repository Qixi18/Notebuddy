import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace, type Feature } from '../components/AppLayout'
import { CourseGate } from '../components/CourseGate'
import { KnowledgeTreeScene, type KnowledgeTreeView } from '../features/forest/KnowledgeTreeScene'
import { NotebookRootMenu } from '../features/forest/NotebookRootMenu'
import { ForestRelationsPanel } from '../features/forest/ForestRelationsPanel'
import { useAutomaticVines } from '../features/forest/useAutomaticVines'
import { useTreeDirectories } from '../features/forest/useTreeDirectories'
import type { ForestCourse } from '../features/forest/types'
import { notebookPath } from '../features/notebook/navigation'
import { selectHomeCourses, readSceneSnapshot, saveSceneSnapshot } from '../features/forest/pageState'
import '../features/forest/forest.css'

export function HomePage() {
  const location = useLocation()
  const state = location.state as { restoreSceneEntry?: string } | null
  return <HomeScene key={state?.restoreSceneEntry ?? location.key} />
}

function HomeScene() {
  const { courses, coursesLoading, createCourse, busy } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { restoreSceneEntry?: string; openCreateCourse?: boolean; pendingFeature?: Feature } | null
  const entry = state?.restoreSceneEntry ?? location.key
  const restored = useRef(readSceneSnapshot(`home:${entry}`)).current
  const chosen = useRef<string[] | undefined>(restored?.courseIds)
  const view = useRef<KnowledgeTreeView | undefined>(restored?.view)
  const [forestCourses, setForestCourses] = useState<ForestCourse[]>([])
  const [root, setRoot] = useState<string>()
  const [createOpen, setCreateOpen] = useState(Boolean(state?.openCreateCourse))
  const [requestedFeature, setRequestedFeature] = useState(state?.pendingFeature)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>()
  const directories = useTreeDirectories()
  const vines = useAutomaticVines(directories.watchKey, directories.settledVersion, directories.refresh)
  const [relationsOpen, setRelationsOpen] = useState(false)
  const [selectedRelation, setSelectedRelation] = useState<string>()
  useEffect(() => {
    let active = true
    void api.getForest().then(result => { if (active) setForestCourses(result.courses) }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '课程树读取失败') })
    return () => { active = false }
  }, [courses])
  if (!chosen.current && !coursesLoading) chosen.current = selectHomeCourses(courses).map(course => course.id)
  const visible = (chosen.current ?? []).flatMap(id => forestCourses.filter(course => course.course_id === id))
  const saveView = (next: KnowledgeTreeView) => { view.current = next; saveSceneSnapshot(`home:${entry}`, { view: next, courseIds: chosen.current ?? [] }) }
  const returnState = { sceneReturn: '/', sceneEntry: entry }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || creating) return
    setCreating(true); setError(undefined)
    try { navigate(`/courses/${(await createCourse(name.trim())).id}`) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '课程创建失败') }
    finally { setCreating(false) }
  }
  return <div className="home-tree-page">
    <header className="forest-header"><div><h1>让知识慢慢生长</h1><p>树根添加资料 · 主枝继续阅读 · 叶子打开知识点</p></div><div className="forest-header-actions"><Link to="/forest">走进知识森林</Link><button onClick={() => setCreateOpen(true)}>新建课程</button></div></header>
    <div className="home-tree-surface">
      <KnowledgeTreeScene key={entry} mode="home" courses={visible} trees={directories.trees} initialView={restored?.view} relations={vines.relations} selectedRelationId={selectedRelation} pinnedNoteIds={vines.relations.filter(relation => relation.status === 'confirmed' && !relation.stale && chosen.current?.includes(relation.source_course_id) && chosen.current?.includes(relation.target_course_id)).slice(0, 6).flatMap(relation => [relation.source_note_id, relation.target_note_id])} onViewChange={saveView} onVisibleCourseIdsChange={directories.watch}
        onRoot={setRoot} onNotebook={(courseId, notebookId) => navigate(notebookPath(courseId, undefined, undefined, notebookId), { state: returnState })}
        onNote={(courseId, notebookId, section) => navigate(notebookPath(courseId, section, undefined, notebookId), { state: returnState })} onRelation={() => setRelationsOpen(true)} />
      {coursesLoading && <p className="forest-scene-message" role="status">正在读取课程…</p>}
      {!coursesLoading && !courses.length && <div className="forest-scene-empty"><h2>从一门课程开始</h2><p>创建课程，然后从树根新建笔记本并上传第一讲。</p><button onClick={() => setCreateOpen(true)}>创建课程</button></div>}
    </div>
    {vines.error && <p role="alert">{vines.error}<button onClick={() => void vines.refresh()}>重试关联</button></p>}
    {Object.values(vines.jobs).filter(job => job.status === 'failed').map(job => <p role="status" key={job.id}>{job.error_message}<button onClick={() => void api.retryForestJob(job.id).then(next => { const id = Object.keys(vines.jobs).find(id => vines.jobs[id].id === job.id); if (id) vines.track(id, next) }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '重试失败'))}>重试关联任务</button></p>)}
    {relationsOpen && <ForestRelationsPanel relations={vines.relations} courses={forestCourses} onLocate={relation => {
      if (!chosen.current?.includes(relation.source_course_id) || !chosen.current?.includes(relation.target_course_id)) {
        navigate(`/forest?relation=${encodeURIComponent(relation.id)}`)
        return
      }
      setSelectedRelation(relation.id); directories.load([relation.source_course_id, relation.target_course_id]); setRelationsOpen(false)
    }} onChange={() => { void vines.refresh(); void directories.refresh() }} onClose={() => setRelationsOpen(false)} />}
    {(error || Object.keys(directories.errors).length > 0) && <p role="alert">{error ?? '部分课程目录读取失败。'}<button onClick={() => directories.load(Object.keys(directories.errors))}>重试目录</button></p>}
    {root && <NotebookRootMenu courseId={root} courseName={courses.find(course => course.id === root)?.name ?? '课程'} onClose={() => setRoot(undefined)} returnState={returnState} />}
    {requestedFeature && <CourseGate feature={requestedFeature} onClose={() => setRequestedFeature(undefined)} />}
    {createOpen && <div className="modal-backdrop"><section className="course-gate-modal" role="dialog" aria-modal="true" aria-label="创建课程" onKeyDown={event => { if (event.key === 'Escape' && !creating) setCreateOpen(false) }}><button className="modal-close" onClick={() => setCreateOpen(false)} disabled={creating} aria-label="关闭">×</button><h2>创建课程</h2><form onSubmit={event => void create(event)}><label>课程名称<input autoFocus maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label><button className="primary-button" disabled={!name.trim() || creating || busy}>创建并打开</button></form>{error && <p role="alert">{error}</p>}</section></div>}
  </div>
}
