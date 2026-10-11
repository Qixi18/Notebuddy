import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { featurePath, useWorkspace } from '../components/AppLayout'
import { ProcessingStatus } from '../components/ProcessingStatus'
import { CourseKnowledgeStructure } from './CourseKnowledgeStructure'

type CourseTab = 'overview' | 'structure'

export function CourseOverviewPage() {
  const { courseId = '' } = useParams()
  const { course, courseContentLoading, materials, notes, graph, job, coursesLoading, refreshCourses } = useWorkspace()
  const [activeTab, setActiveTab] = useState<CourseTab>('overview')
  const navigate = useNavigate()

  if (coursesLoading) return <div className="page-loading" role="status">正在读取课程…</div>
  if (!course) {
    return (
      <section className="route-state-card" role="alert">
        <span className="route-state-symbol">?</span>
        <h1>找不到这门课程</h1>
        <p>课程可能已被移除，或链接中的课程编号无效。</p>
        <Link className="primary-button link-button" to="/">返回首页选择课程</Link>
        <button className="text-button" onClick={() => void refreshCourses()}>重新读取课程</button>
      </section>
    )
  }

  const latestMaterial = materials[0]
  const materialCount = materials.length
  const readyCount = materials.filter((material) => material.status === 'completed').length

  return (
    <div className="course-overview course-workspace page-enter">
      <header className="course-workspace-heading">
        <div>
          <h1>{course.name}</h1>
          <p>{course.description || '把课程资料、学习笔记和知识结构整理在一起。'}</p>
        </div>
        <div className="course-workspace-actions">
          <button className="secondary-button" type="button" onClick={() => navigate('/', { state: { openCreateCourse: true } })}>＋ 新建课程</button>
          <Link className="primary-button link-button" to={featurePath(courseId, 'materials')}>上传课程资料</Link>
        </div>
      </header>

      <div className="course-tabs" role="tablist" aria-label="课程内容">
        <button id="course-tab-overview" type="button" role="tab" aria-selected={activeTab === 'overview'} aria-controls="course-panel-overview" className={activeTab === 'overview' ? 'course-tab-active' : ''} onClick={() => setActiveTab('overview')}>课程概览</button>
        <button id="course-tab-structure" type="button" role="tab" aria-selected={activeTab === 'structure'} aria-controls="course-panel-structure" className={activeTab === 'structure' ? 'course-tab-active' : ''} onClick={() => setActiveTab('structure')}>知识结构</button>
      </div>

      {activeTab === 'overview' ? (
        <section id="course-panel-overview" className="course-overview-panel" role="tabpanel" aria-labelledby="course-tab-overview">
          <div className="course-overview-intro">
            <div className="course-overview-mark" aria-hidden="true">⌂</div>
            <div><h2>继续这门课程</h2><p>{materialCount ? `${readyCount} 份资料已完成整理。` : '上传课件后，NoteBuddy 会将来源、知识结构和学习笔记归入当前课程。'}</p></div>
          </div>

          <div className="course-entry-list">
            <Link className="course-entry-row" to={featurePath(courseId, 'materials')}>
              <span className="course-entry-icon" aria-hidden="true">▱</span>
              <span className="course-entry-copy"><strong>课程资料</strong><small>{materialCount ? `${materialCount} 份资料 · 查看解析状态与页码来源` : '上传课件并查看解析状态与页码来源'}</small></span>
              <span className="course-entry-arrow" aria-hidden="true">→</span>
            </Link>
            <Link className="course-entry-row" to={featurePath(courseId, 'notes')}>
              <span className="course-entry-icon course-entry-icon-notes" aria-hidden="true">▤</span>
              <span className="course-entry-copy"><strong>课程笔记</strong><small>{notes.length ? `${notes.length} 条笔记 · 阅读、编辑并核对引用` : '阅读整理内容，或从已解析的资料开始生成'}</small></span>
              <span className="course-entry-arrow" aria-hidden="true">→</span>
            </Link>
            <button className="course-entry-row" type="button" onClick={() => setActiveTab('structure')}>
              <span className="course-entry-icon course-entry-icon-structure" aria-hidden="true">⌘</span>
              <span className="course-entry-copy"><strong>知识结构</strong><small>{graph.nodes.length ? `${graph.nodes.length} 个知识点 · 查看课程脉络与关联` : '从课程资料整理知识点和概念关联'}</small></span>
              <span className="course-entry-arrow" aria-hidden="true">→</span>
            </button>
          </div>

          {courseContentLoading ? <p className="course-loading-inline" role="status">正在读取课程内容…</p> : latestMaterial ? (
            <section className="course-latest-material" aria-label="最近课程资料">
              <div><span>最近课程资料</span><strong>{latestMaterial.lecture_title}</strong><small>{latestMaterial.original_filename}</small></div>
              <ProcessingStatus job={job?.material_id === latestMaterial.id ? job : undefined} material={latestMaterial} />
            </section>
          ) : <p className="course-first-upload-hint">先从一份 PPTX、PDF 或 DOCX 课件开始。</p>}
        </section>
      ) : (
        <section id="course-panel-structure" className="course-structure-panel" role="tabpanel" aria-labelledby="course-tab-structure">
          <CourseKnowledgeStructure />
        </section>
      )}
    </div>
  )
}
