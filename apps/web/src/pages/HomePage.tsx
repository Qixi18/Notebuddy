import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace, type Feature } from '../components/AppLayout'
import { CourseGate } from '../components/CourseGate'
import { HomeCourseGarden } from '../features/home/HomeCourseGarden'
import { NotebookRootMenu } from '../features/notebook/NotebookRootMenu'
import { ForestRelationsPanel } from '../features/forest/ForestRelationsPanel'
import { useTreeDirectories } from '../features/forest/useTreeDirectories'
import { useNotebookRelations } from '../features/forest/useNotebookRelations'
import type { ForestCourse, ForestSearchResult } from '../features/forest/types'
import { notebookPath } from '../features/notebook/navigation'
import { selectHomeCourses } from '../features/workspace/homeCourses'
import { HomeSearch } from '../features/home/HomeSearch'
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
  const [forestCourses, setForestCourses] = useState<ForestCourse[]>([])
  const [forestLoading, setForestLoading] = useState(true)
  const [forestError, setForestError] = useState<string>()
  const [forestReload, setForestReload] = useState(0)
  const [root, setRoot] = useState<string>()
  const [createOpen, setCreateOpen] = useState(Boolean(state?.openCreateCourse))
  const [requestedFeature, setRequestedFeature] = useState(state?.pendingFeature)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>()
  const directories = useTreeDirectories()
  const vines = useNotebookRelations(directories.trees, directories.settledVersion, directories.watchKey, directories.refresh)
  const [relationsOpen, setRelationsOpen] = useState(false)
  const [selectedRelation, setSelectedRelation] = useState<string>()

  useEffect(() => {
    let active = true
    setForestLoading(true); setForestError(undefined)
    void api.getForest().then(result => { if (active) setForestCourses(result.courses) }).catch((cause: unknown) => { if (active) setForestError(cause instanceof Error ? cause.message : '课程树读取失败') }).finally(() => { if (active) setForestLoading(false) })
    return () => { active = false }
  }, [courses, forestReload])

  useEffect(() => {
    const refresh = () => setForestReload(value => value + 1)
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [])
  const visible = selectHomeCourses(forestCourses)
  const returnState = { sceneReturn: '/', sceneEntry: entry }

  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || creating) return
    setCreating(true); setError(undefined)
    try { navigate(`/courses/${(await createCourse(name.trim())).id}`) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '课程创建失败') }
    finally { setCreating(false) }
  }

  return <div className="home-tree-page home-garden-page">
    <div className="home-canvas">
      <header className="home-garden-header">
        <div><span className="home-garden-eyebrow">我的学习花园</span><h1>让知识慢慢生长</h1><p>在知识森林选择最多三门正在学的课程，从一片叶子继续今天的学习。</p></div>
        <div className="home-garden-actions"><Link to="/forest">走进知识森林<span aria-hidden="true"> ↗</span></Link><button onClick={() => setCreateOpen(true)}><span aria-hidden="true">＋ </span>新建课程</button></div>
      </header>
      <div className="home-garden-toolbar">
        <HomeSearch courses={courses} onCourse={id => navigate(`/forest?course=${encodeURIComponent(id)}`)} onNote={(item: ForestSearchResult) => navigate(item.block_id ? `/courses/${item.course_id}/notebooks/${item.notebook_id}?section=${encodeURIComponent(item.block_id)}` : `/courses/${item.course_id}/notebooks/${item.notebook_id}`, { state: returnState })} />
        <span className="home-view-caption">随窗口自适应 <span aria-hidden="true">·</span> 点击枝叶继续阅读</span>
        {vines.records.length > 0 && <button className="home-relations-link" onClick={() => { setSelectedRelation(undefined); setRelationsOpen(true) }}>查看知识关联 ↗</button>}
      </div>
      <div className="home-tree-surface">
        {visible.length > 0 && <HomeCourseGarden key={entry} courses={visible} trees={directories.trees} onVisibleCourseIdsChange={directories.watch} relations={vines.relations}
          onRoot={setRoot} onNotebook={(courseId, notebookId) => navigate(notebookPath(courseId, undefined, undefined, notebookId), { state: returnState })}
          onNote={(courseId, notebookId, section) => navigate(notebookPath(courseId, section, undefined, notebookId), { state: returnState })} selectedRelationId={selectedRelation} onRelation={relation => { setSelectedRelation(relation.id); setRelationsOpen(true) }} />}
        {(coursesLoading || forestLoading) && <p className="forest-scene-message" role="status">正在读取课程…</p>}
        {!coursesLoading && !forestLoading && !forestError && !visible.length && <div className="home-learning-empty"><h2>{courses.length ? '选择你正在学的课程' : '从一门课程开始'}</h2><p>{courses.length ? '从知识森林把课程树放到首页，最多三棵。其他课程随时可以在森林中找到。' : '创建课程，然后从树根新建笔记本并上传第一讲。'}</p>{courses.length ? <Link to="/forest?home=manage">选择首页课程</Link> : <button onClick={() => setCreateOpen(true)}>创建课程</button>}</div>}
      </div>
      <footer className="home-garden-footer" aria-label="知识树操作说明"><span><i aria-hidden="true">＋</i><b>根部</b> 添加资料</span><span><i aria-hidden="true">⌁</i><b>主枝</b> 继续阅读</span><span><i aria-hidden="true">❧</i><b>叶子</b> 打开笔记</span><small>鼠标停在叶子上预览知识点，点击进入正文</small></footer>
      {forestError && <p role="alert">{forestError}<button onClick={() => setForestReload(value => value + 1)}>重新读取课程树</button></p>}
      {vines.error && <p role="alert">{vines.error}<button onClick={() => void vines.refresh()}>重试关联</button></p>}
      {Object.values(vines.jobs).filter(job => job.status === 'failed').map(job => <p role="status" key={job.id}>{job.error_message}<button onClick={() => void api.retryForestJob(job.id).then(next => { const id = Object.keys(vines.jobs).find(id => vines.jobs[id].id === job.id); if (id) vines.track(id, next) }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '重试失败'))}>重试关联任务</button></p>)}
      {(error || Object.keys(directories.errors).length > 0) && <p role="alert">{error ?? '部分课程目录读取失败。'}<button onClick={() => directories.load(Object.keys(directories.errors))}>重试目录</button></p>}
    </div>

    {relationsOpen && <ForestRelationsPanel relations={vines.records} courses={forestCourses} selectedRelationId={selectedRelation} onLocate={relation => navigate(`/forest?relation=${encodeURIComponent(relation.id)}`)} onChanged={() => { void vines.refresh(); void directories.refresh() }} onClose={() => setRelationsOpen(false)} />}
    {root && <NotebookRootMenu courseId={root} courseName={courses.find(course => course.id === root)?.name ?? '课程'} onClose={() => setRoot(undefined)} returnState={returnState} />}
    {requestedFeature && <CourseGate feature={requestedFeature} onClose={() => setRequestedFeature(undefined)} />}
    {createOpen && <div className="modal-backdrop"><section className="course-gate-modal" role="dialog" aria-modal="true" aria-label="创建课程" onKeyDown={event => { if (event.key === 'Escape' && !creating) setCreateOpen(false) }}><button className="modal-close" onClick={() => setCreateOpen(false)} disabled={creating} aria-label="关闭">×</button><h2>创建课程</h2><form onSubmit={event => void create(event)}><label>课程名称<input autoFocus maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label><button className="primary-button" disabled={!name.trim() || creating || busy}>创建并打开</button></form>{error && <p role="alert">{error}</p>}</section></div>}
  </div>
}
